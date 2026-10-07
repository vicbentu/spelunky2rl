// spelunky2rl's frame capture: an implicit Vulkan layer between DXVK and the driver, enabled with
// SPELUNKY2RL_CAPTURE_LAYER=1 (manifest: capture.json). On every vkQueuePresentKHR it copies the
// presented image to the file SPELUNKY2RL_CAPTURE and counts the frame; Python (engine/frames/
// vulkan.py) waits for the count the mod sent with the state and reads the pixels.
//
// The file is a 4096-byte header (Header below, little-endian) followed by the pixels, `stride` bytes
// per row, in the swapchain's `format`. The copy is waited for before the count moves and before the
// present goes on, so when Python sees the count the pixels are there and are the frame's.
#include <vulkan/vulkan.h>
#include <vulkan/vk_layer.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define EXPORT __attribute__((visibility("default")))
#define MAX 16
#define HEADER 4096
#define MAGIC 0x53324c52  // "RL2S"
#define VERSION 1

typedef struct {
    uint32_t magic, version;
    uint64_t frame;          // frames presented so far; written last, with release order
    uint32_t width, height, format, stride;
    uint64_t copy_ns;        // time from the present call to the pixels in the file, last frame
} Header;

// Instances, devices and queues are told apart by their loader dispatch table, the first pointer
static void *key(const void *h) { return *(void **)h; }

typedef struct {
    void *key;
    PFN_vkGetInstanceProcAddr gipa;
    PFN_vkDestroyInstance DestroyInstance;
    PFN_vkGetPhysicalDeviceMemoryProperties GetPhysicalDeviceMemoryProperties;
} Inst;

typedef struct {
    VkSwapchainKHR handle;
    VkImage images[16];
    uint32_t count;
    VkExtent2D extent;
    VkFormat format;
    VkBuffer buffer;         // host-visible, where the presented image is copied
    VkDeviceMemory memory;
    void *mapped;
} Swap;

typedef struct {
    void *key;
    VkDevice device;
    VkPhysicalDevice phys;
    PFN_vkGetDeviceProcAddr gdpa;
    PFN_vkSetDeviceLoaderData set_loader_data;
    VkQueue queues[16];
    uint32_t families[16], nqueues;
    Swap swaps[4];
    VkCommandPool pools[16];   // per queue family
    VkCommandBuffer cmds[16];
    VkFence fence;
#define F(name) PFN_vk##name name;
    F(DestroyDevice) F(GetDeviceQueue) F(GetDeviceQueue2) F(CreateSwapchainKHR) F(DestroySwapchainKHR)
    F(GetSwapchainImagesKHR) F(QueuePresentKHR) F(CreateCommandPool) F(AllocateCommandBuffers)
    F(BeginCommandBuffer) F(EndCommandBuffer) F(CmdPipelineBarrier) F(CmdCopyImageToBuffer)
    F(QueueSubmit) F(CreateFence) F(WaitForFences) F(ResetFences) F(CreateBuffer)
    F(GetBufferMemoryRequirements) F(AllocateMemory) F(BindBufferMemory) F(MapMemory)
    F(ResetCommandBuffer) F(DestroyBuffer) F(FreeMemory) F(UnmapMemory)
#undef F
} Dev;

static Inst insts[MAX];
static Dev devs[MAX];
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;

static Inst *inst_of(const void *h) {
    for (int i = 0; i < MAX; i++) if (insts[i].key && insts[i].key == key(h)) return &insts[i];
    return NULL;
}
static Dev *dev_of(const void *h) {
    for (int i = 0; i < MAX; i++) if (devs[i].key && devs[i].key == key(h)) return &devs[i];
    return NULL;
}

// Formats with 4 bytes per pixel, the only ones copied. Python reads the format from the header and
// refuses any other (the count still moves, so it does not wait for its timeout).
static int four_bytes(VkFormat f) {
    return f == VK_FORMAT_B8G8R8A8_UNORM || f == VK_FORMAT_B8G8R8A8_SRGB ||
           f == VK_FORMAT_R8G8B8A8_UNORM || f == VK_FORMAT_R8G8B8A8_SRGB;
}

// ---- the file ----
static const char *path;     // SPELUNKY2RL_CAPTURE; NULL: present without copying
static Header *shm;
static size_t shm_size;

// Map the file with room for `pixels` bytes, growing it if the swapchain got bigger. The count goes on.
static void map_file(size_t pixels) {
    size_t size = HEADER + pixels;
    if (shm && size <= shm_size) return;
    int fd = open(path, O_RDWR | O_CREAT, 0666);
    if (fd < 0) { perror("spelunky2rl capture layer: open"); return; }
    if (ftruncate(fd, size) != 0) { perror("spelunky2rl capture layer: ftruncate"); close(fd); return; }
    void *m = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (m == MAP_FAILED) { perror("spelunky2rl capture layer: mmap"); return; }
    uint64_t frame = shm ? shm->frame : 0;
    if (shm) munmap(shm, shm_size);
    shm = m; shm_size = size;
    shm->magic = MAGIC; shm->version = VERSION; shm->frame = frame;
}

// ---- instance ----
static VKAPI_ATTR VkResult VKAPI_CALL CreateInstance(const VkInstanceCreateInfo *ci, const VkAllocationCallbacks *a, VkInstance *out) {
    VkLayerInstanceCreateInfo *chain = (VkLayerInstanceCreateInfo *)ci->pNext;
    while (chain && !(chain->sType == VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO && chain->function == VK_LAYER_LINK_INFO))
        chain = (VkLayerInstanceCreateInfo *)chain->pNext;
    if (!chain) return VK_ERROR_INITIALIZATION_FAILED;
    PFN_vkGetInstanceProcAddr gipa = chain->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    chain->u.pLayerInfo = chain->u.pLayerInfo->pNext;
    PFN_vkCreateInstance create = (PFN_vkCreateInstance)gipa(NULL, "vkCreateInstance");
    VkResult r = create(ci, a, out);
    if (r != VK_SUCCESS) return r;
    path = getenv("SPELUNKY2RL_CAPTURE");
    pthread_mutex_lock(&lock);
    for (int i = 0; i < MAX; i++) if (!insts[i].key) {
        insts[i].key = key(*out);
        insts[i].gipa = gipa;
        insts[i].DestroyInstance = (PFN_vkDestroyInstance)gipa(*out, "vkDestroyInstance");
        insts[i].GetPhysicalDeviceMemoryProperties = (PFN_vkGetPhysicalDeviceMemoryProperties)gipa(*out, "vkGetPhysicalDeviceMemoryProperties");
        break;
    }
    pthread_mutex_unlock(&lock);
    return r;
}

static VKAPI_ATTR void VKAPI_CALL DestroyInstance(VkInstance instance, const VkAllocationCallbacks *a) {
    Inst *in = inst_of(instance);
    if (!in) return;
    PFN_vkDestroyInstance destroy = in->DestroyInstance;
    in->key = NULL;
    destroy(instance, a);
}

// ---- device ----
static VKAPI_ATTR VkResult VKAPI_CALL CreateDevice(VkPhysicalDevice phys, const VkDeviceCreateInfo *ci, const VkAllocationCallbacks *a, VkDevice *out) {
    VkLayerDeviceCreateInfo *link = (VkLayerDeviceCreateInfo *)ci->pNext, *cb = (VkLayerDeviceCreateInfo *)ci->pNext;
    while (link && !(link->sType == VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO && link->function == VK_LAYER_LINK_INFO))
        link = (VkLayerDeviceCreateInfo *)link->pNext;
    while (cb && !(cb->sType == VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO && cb->function == VK_LOADER_DATA_CALLBACK))
        cb = (VkLayerDeviceCreateInfo *)cb->pNext;
    if (!link) return VK_ERROR_INITIALIZATION_FAILED;
    PFN_vkGetInstanceProcAddr gipa = link->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr gdpa = link->u.pLayerInfo->pfnNextGetDeviceProcAddr;
    link->u.pLayerInfo = link->u.pLayerInfo->pNext;
    PFN_vkCreateDevice create = (PFN_vkCreateDevice)gipa(NULL, "vkCreateDevice");
    if (!create) {
        Inst *in = inst_of(phys);
        if (in) create = (PFN_vkCreateDevice)in->gipa(NULL, "vkCreateDevice");
    }
    VkResult r = create(phys, ci, a, out);
    if (r != VK_SUCCESS) return r;
    pthread_mutex_lock(&lock);
    for (int i = 0; i < MAX; i++) if (!devs[i].key) {
        Dev *d = &devs[i];
        memset(d, 0, sizeof *d);
        d->key = key(*out); d->device = *out; d->phys = phys; d->gdpa = gdpa;
        d->set_loader_data = cb ? cb->u.pfnSetDeviceLoaderData : NULL;
#define F(name) d->name = (PFN_vk##name)gdpa(*out, "vk" #name);
        F(DestroyDevice) F(GetDeviceQueue) F(GetDeviceQueue2) F(CreateSwapchainKHR) F(DestroySwapchainKHR)
        F(GetSwapchainImagesKHR) F(QueuePresentKHR) F(CreateCommandPool) F(AllocateCommandBuffers)
        F(BeginCommandBuffer) F(EndCommandBuffer) F(CmdPipelineBarrier) F(CmdCopyImageToBuffer)
        F(QueueSubmit) F(CreateFence) F(WaitForFences) F(ResetFences) F(CreateBuffer)
        F(GetBufferMemoryRequirements) F(AllocateMemory) F(BindBufferMemory) F(MapMemory)
        F(ResetCommandBuffer) F(DestroyBuffer) F(FreeMemory) F(UnmapMemory)
#undef F
        VkFenceCreateInfo fci = {VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
        d->CreateFence(*out, &fci, NULL, &d->fence);
        break;
    }
    pthread_mutex_unlock(&lock);
    return r;
}

static VKAPI_ATTR void VKAPI_CALL DestroyDevice(VkDevice device, const VkAllocationCallbacks *a) {
    Dev *d = dev_of(device);
    if (!d) return;
    PFN_vkDestroyDevice destroy = d->DestroyDevice;
    d->key = NULL;
    destroy(device, a);
}

// The copy is submitted to the queue that presents, so the layer needs that queue's family
static void remember_queue(Dev *d, uint32_t family, VkQueue q) {
    for (uint32_t i = 0; i < d->nqueues; i++) if (d->queues[i] == q) return;
    if (d->nqueues < 16) { d->queues[d->nqueues] = q; d->families[d->nqueues++] = family; }
}

static VKAPI_ATTR void VKAPI_CALL GetDeviceQueue(VkDevice device, uint32_t family, uint32_t index, VkQueue *q) {
    Dev *d = dev_of(device);
    d->GetDeviceQueue(device, family, index, q);
    remember_queue(d, family, *q);
}

static VKAPI_ATTR void VKAPI_CALL GetDeviceQueue2(VkDevice device, const VkDeviceQueueInfo2 *info, VkQueue *q) {
    Dev *d = dev_of(device);
    d->GetDeviceQueue2(device, info, q);
    remember_queue(d, info->queueFamilyIndex, *q);
}

static uint32_t memory_type(Dev *d, uint32_t bits, VkMemoryPropertyFlags want) {
    VkPhysicalDeviceMemoryProperties p;
    inst_of(d->phys)->GetPhysicalDeviceMemoryProperties(d->phys, &p);
    for (uint32_t i = 0; i < p.memoryTypeCount; i++)
        if ((bits & (1u << i)) && (p.memoryTypes[i].propertyFlags & want) == want) return i;
    return UINT32_MAX;
}

static VKAPI_ATTR VkResult VKAPI_CALL CreateSwapchainKHR(VkDevice device, const VkSwapchainCreateInfoKHR *ci, const VkAllocationCallbacks *a, VkSwapchainKHR *out) {
    Dev *d = dev_of(device);
    VkSwapchainCreateInfoKHR mine = *ci;
    mine.imageUsage |= VK_IMAGE_USAGE_TRANSFER_SRC_BIT;  // so the presented image can be copied
    VkResult r = d->CreateSwapchainKHR(device, &mine, a, out);
    if (r != VK_SUCCESS || !path) return r;
    Swap *s = NULL;
    for (int i = 0; i < 4; i++) if (!d->swaps[i].handle) { s = &d->swaps[i]; break; }
    if (!s) { fprintf(stderr, "spelunky2rl capture layer: more than 4 swapchains, not capturing the new one\n"); return r; }
    memset(s, 0, sizeof *s);
    s->handle = *out; s->extent = ci->imageExtent; s->format = ci->imageFormat;
    s->count = 16;
    d->GetSwapchainImagesKHR(device, *out, &s->count, s->images);
    if (!four_bytes(s->format)) {
        fprintf(stderr, "spelunky2rl capture layer: swapchain format %d is not supported\n", s->format);
        return r;
    }
    VkDeviceSize size = (VkDeviceSize)s->extent.width * s->extent.height * 4;
    VkBufferCreateInfo bci = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, NULL, 0, size, VK_BUFFER_USAGE_TRANSFER_DST_BIT, VK_SHARING_MODE_EXCLUSIVE};
    d->CreateBuffer(device, &bci, NULL, &s->buffer);
    VkMemoryRequirements req;
    d->GetBufferMemoryRequirements(device, s->buffer, &req);
    // cached memory makes the CPU's read of it several times faster where the driver has it
    uint32_t type = memory_type(d, req.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT | VK_MEMORY_PROPERTY_HOST_CACHED_BIT);
    if (type == UINT32_MAX) type = memory_type(d, req.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    VkMemoryAllocateInfo mai = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL, req.size, type};
    d->AllocateMemory(device, &mai, NULL, &s->memory);
    d->BindBufferMemory(device, s->buffer, s->memory, 0);
    d->MapMemory(device, s->memory, 0, VK_WHOLE_SIZE, 0, &s->mapped);
    return r;
}

static VKAPI_ATTR void VKAPI_CALL DestroySwapchainKHR(VkDevice device, VkSwapchainKHR sc, const VkAllocationCallbacks *a) {
    Dev *d = dev_of(device);
    for (int i = 0; i < 4; i++) if (sc && d->swaps[i].handle == sc) {
        Swap *s = &d->swaps[i];
        if (s->buffer) {
            d->UnmapMemory(device, s->memory);
            d->DestroyBuffer(device, s->buffer, NULL);
            d->FreeMemory(device, s->memory, NULL);
        }
        s->handle = VK_NULL_HANDLE;
    }
    d->DestroySwapchainKHR(device, sc, a);
}

static VkCommandBuffer command_buffer(Dev *d, VkQueue q) {
    uint32_t family = 0;
    for (uint32_t i = 0; i < d->nqueues; i++) if (d->queues[i] == q) family = d->families[i];
    if (!d->pools[family]) {
        VkCommandPoolCreateInfo pci = {VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, NULL, VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, family};
        d->CreateCommandPool(d->device, &pci, NULL, &d->pools[family]);
        VkCommandBufferAllocateInfo ai = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, NULL, d->pools[family], VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1};
        d->AllocateCommandBuffers(d->device, &ai, &d->cmds[family]);
        // a layer's own command buffers need the loader's dispatch pointer set by hand
        if (d->set_loader_data) d->set_loader_data(d->device, d->cmds[family]);
        else *(void **)d->cmds[family] = key(d->device);
    }
    return d->cmds[family];
}

static uint64_t now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + t.tv_nsec;
}

// Count a presented frame that was not copied (unsupported format): Python sees the format and fails
static void count_only(Swap *s) {
    map_file(0);
    if (!shm) return;
    shm->width = s->extent.width; shm->height = s->extent.height; shm->format = s->format; shm->stride = 0;
    __atomic_store_n(&shm->frame, shm->frame + 1, __ATOMIC_RELEASE);
}

static VKAPI_ATTR VkResult VKAPI_CALL QueuePresentKHR(VkQueue queue, const VkPresentInfoKHR *info) {
    Dev *d = dev_of(queue);
    Swap *s = NULL;
    for (int i = 0; i < 4 && path && info->swapchainCount; i++)
        if (d->swaps[i].handle == info->pSwapchains[0]) s = &d->swaps[i];
    if (!s) return d->QueuePresentKHR(queue, info);
    if (!s->buffer) { count_only(s); return d->QueuePresentKHR(queue, info); }

    uint64_t t0 = now_ns();
    VkImage image = s->images[info->pImageIndices[0]];
    VkCommandBuffer cmd = command_buffer(d, queue);
    d->ResetCommandBuffer(cmd, 0);
    VkCommandBufferBeginInfo bi = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, NULL, VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
    d->BeginCommandBuffer(cmd, &bi);
    VkImageSubresourceRange range = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    VkImageMemoryBarrier to_src = {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, NULL, VK_ACCESS_MEMORY_WRITE_BIT, VK_ACCESS_TRANSFER_READ_BIT,
        VK_IMAGE_LAYOUT_PRESENT_SRC_KHR, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED, image, range};
    d->CmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &to_src);
    VkBufferImageCopy region = {0, 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, {0, 0, 0}, {s->extent.width, s->extent.height, 1}};
    d->CmdCopyImageToBuffer(cmd, image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, s->buffer, 1, &region);
    VkImageMemoryBarrier back = to_src;
    back.srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT; back.dstAccessMask = 0;
    back.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL; back.newLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
    VkBufferMemoryBarrier host = {VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER, NULL, VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_HOST_READ_BIT,
        VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED, s->buffer, 0, VK_WHOLE_SIZE};
    d->CmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT | VK_PIPELINE_STAGE_HOST_BIT, 0, 0, NULL, 1, &host, 1, &back);
    d->EndCommandBuffer(cmd);

    // the copy waits for what the present would have waited for (the frame being drawn); the
    // present then needs no semaphores, as the fence below already waited for the copy
    VkPipelineStageFlags stages[8];
    uint32_t waits = info->waitSemaphoreCount < 8 ? info->waitSemaphoreCount : 8;
    for (uint32_t i = 0; i < waits; i++) stages[i] = VK_PIPELINE_STAGE_ALL_COMMANDS_BIT;
    VkSubmitInfo si = {VK_STRUCTURE_TYPE_SUBMIT_INFO, NULL, waits, info->pWaitSemaphores, stages, 1, &cmd, 0, NULL};
    d->ResetFences(d->device, 1, &d->fence);
    d->QueueSubmit(queue, 1, &si, d->fence);
    d->WaitForFences(d->device, 1, &d->fence, VK_TRUE, UINT64_MAX);

    uint32_t stride = s->extent.width * 4;
    map_file((size_t)stride * s->extent.height);
    if (shm) {
        memcpy((char *)shm + HEADER, s->mapped, (size_t)stride * s->extent.height);
        shm->width = s->extent.width; shm->height = s->extent.height;
        shm->format = s->format; shm->stride = stride;
        shm->copy_ns = now_ns() - t0;
        __atomic_store_n(&shm->frame, shm->frame + 1, __ATOMIC_RELEASE);
    }

    VkPresentInfoKHR mine = *info;
    mine.waitSemaphoreCount = 0; mine.pWaitSemaphores = NULL;
    return d->QueuePresentKHR(queue, &mine);
}

// ---- dispatch ----
static PFN_vkVoidFunction device_hook(const char *name);

EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL s2rl_GetDeviceProcAddr(VkDevice device, const char *name) {
    PFN_vkVoidFunction f = device_hook(name);
    if (f) return f;
    Dev *d = dev_of(device);
    return d ? d->gdpa(device, name) : NULL;
}

EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL s2rl_GetInstanceProcAddr(VkInstance instance, const char *name) {
    if (!strcmp(name, "vkGetInstanceProcAddr")) return (PFN_vkVoidFunction)s2rl_GetInstanceProcAddr;
    if (!strcmp(name, "vkCreateInstance")) return (PFN_vkVoidFunction)CreateInstance;
    if (!strcmp(name, "vkDestroyInstance")) return (PFN_vkVoidFunction)DestroyInstance;
    if (!strcmp(name, "vkCreateDevice")) return (PFN_vkVoidFunction)CreateDevice;
    PFN_vkVoidFunction f = device_hook(name);
    if (f) return f;
    if (!instance) return NULL;
    Inst *in = inst_of(instance);
    return in ? in->gipa(instance, name) : NULL;
}

static PFN_vkVoidFunction device_hook(const char *name) {
#define H(n) if (!strcmp(name, "vk" #n)) return (PFN_vkVoidFunction)n;
    H(DestroyDevice) H(GetDeviceQueue) H(GetDeviceQueue2) H(CreateSwapchainKHR) H(DestroySwapchainKHR) H(QueuePresentKHR)
#undef H
    if (!strcmp(name, "vkGetDeviceProcAddr")) return (PFN_vkVoidFunction)s2rl_GetDeviceProcAddr;
    return NULL;
}
