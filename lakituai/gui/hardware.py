"""GPU VRAM detection for the GUI.

Used to warn the user when their GPU has too little VRAM for the chat
model (qwen3:4b needs ~6 GB for optimal performance). Detection avoids
importing torch unless nvidia-smi is unavailable.
"""

import ctypes
import shutil
import subprocess
import sys

# The chat model (qwen3:4b) needs roughly this much VRAM to run fast.
WARNING_THRESHOLD_GB = 6.0

# Vulkan constants
_VK_SUCCESS = 0
_VK_MEMORY_HEAP_DEVICE_LOCAL_BIT = 0x00000001
_VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1


def get_total_vram_gb() -> float | None:
    """Return total GPU VRAM in GB, or None if it cannot be determined.

    Tries, in order: `nvidia-smi` (NVIDIA), the Vulkan API via ctypes
    (NVIDIA/AMD/Intel), and torch's CUDA properties as a last resort.
    """
    for detector in (_from_nvidia_smi, _from_vulkan, _from_torch):
        vram = detector()
        if vram is not None:
            return vram
    return None


def vram_warning_message(vram_gb: float | None) -> str | None:
    """Return the low-VRAM warning text, or None if VRAM is fine/unknown.

    Args:
        vram_gb: Total GPU VRAM in GB (None = could not be detected).

    Returns:
        A short warning string, or None when no warning is needed.
    """
    if vram_gb is None or vram_gb >= WARNING_THRESHOLD_GB:
        return None
    gb = f"{vram_gb:.1f} GB"
    return (
        f"Low VRAM ({gb}): the chat model needs ~6 GB of GPU memory "
        "to run fast. Responses may be slow."
    )


def _from_nvidia_smi() -> float | None:
    """Query total VRAM via nvidia-smi (MiB -> GB), or None on any failure."""
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        ).strip().splitlines()
        if not out:
            return None
        return int(out[0].strip()) / 1024.0
    except Exception:
        return None


def _from_vulkan() -> float | None:
    """Read total VRAM through the Vulkan API via ctypes (no extra deps).

    Works on any GPU with Vulkan drivers: NVIDIA, AMD and Intel. Returns
    the sum of the device-local memory heaps of the first physical device,
    or None if Vulkan is unavailable.

    Runs in a subprocess with a hard timeout: with software Vulkan
    (llvmpipe) the loader can hang, so we never block the GUI.
    """
    probe = (
        "from lakituai.gui.hardware import _vulkan_probe_raw;"
        "print(_vulkan_probe_raw())"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        text = result.stdout.strip()
        if not text or text == "None":
            return None
        return float(text)
    except Exception:
        return None


def _vulkan_probe_raw() -> float | None:
    """Vulkan probe run inside the subprocess; returns GB or None."""
    try:
        lib = _load_vulkan_library()
        if lib is None:
            return None

        class VkInstanceCreateInfo(ctypes.Structure):
            _fields_ = [
                ("s_type", ctypes.c_int32),
                ("p_next", ctypes.c_void_p),
                ("flags", ctypes.c_uint32),
                ("p_application_info", ctypes.c_void_p),
                ("enabled_layer_count", ctypes.c_uint32),
                ("pp_enabled_layer_names", ctypes.c_void_p),
                ("enabled_extension_count", ctypes.c_uint32),
                ("pp_enabled_extension_names", ctypes.c_void_p),
            ]

        create_info = VkInstanceCreateInfo(
            s_type=_VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        )

        lib.vkCreateInstance.restype = ctypes.c_int32
        lib.vkCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        instance = ctypes.c_void_p()
        if lib.vkCreateInstance(ctypes.byref(create_info), None, ctypes.byref(instance)) != _VK_SUCCESS:
            return None

        try:
            lib.vkEnumeratePhysicalDevices.restype = ctypes.c_int32
            lib.vkEnumeratePhysicalDevices.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.c_void_p,
            ]

            count = ctypes.c_uint32()
            if lib.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None) != _VK_SUCCESS:
                return None
            if count.value == 0:
                return None

            devices = (ctypes.c_void_p * count.value)()
            if lib.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), devices) != _VK_SUCCESS:
                return None

            if _vulkan_device_is_cpu(lib, devices[0]):
                return None
            return _vulkan_device_local_vram(lib, devices[0])
        finally:
            try:
                lib.vkDestroyInstance.restype = None
                lib.vkDestroyInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                lib.vkDestroyInstance(instance, None)
            except Exception:
                pass
    except Exception:
        return None


def _load_vulkan_library():
    """Try common Vulkan loader names per platform, or None if absent."""
    names = (
        "libvulkan.so.1",
        "libvulkan.so",
        "vulkan-1.dll",
        "libvulkan.dylib",
        "libMoltenVK.dylib",
    )
    for name in names:
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    return None


def _vulkan_device_is_cpu(lib, device) -> bool:
    """True if the Vulkan device is a CPU software renderer (e.g. llvmpipe)."""

    class VkPhysicalDeviceProperties(ctypes.Structure):
        _fields_ = [
            ("api_version", ctypes.c_uint32),
            ("driver_version", ctypes.c_uint32),
            ("vendor_id", ctypes.c_uint32),
            ("device_id", ctypes.c_uint32),
            ("device_type", ctypes.c_uint32),
        ]

    lib.vkGetPhysicalDeviceProperties.restype = None
    lib.vkGetPhysicalDeviceProperties.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    props = VkPhysicalDeviceProperties()
    lib.vkGetPhysicalDeviceProperties(device, ctypes.byref(props))
    # VK_PHYSICAL_DEVICE_TYPE_CPU == 4 (llvmpipe, lavapipe, etc.)
    return props.device_type == 4


def _vulkan_device_local_vram(lib, device) -> float | None:
    """Sum the device-local memory heaps (bytes) of a Vulkan device, in GB."""

    class VkMemoryHeap(ctypes.Structure):
        _fields_ = [
            ("size", ctypes.c_uint64),
            ("flags", ctypes.c_uint32),
        ]

    class VkMemoryType(ctypes.Structure):
        _fields_ = [
            ("property_flags", ctypes.c_uint32),
            ("heap_index", ctypes.c_uint32),
        ]

    class VkPhysicalDeviceMemoryProperties(ctypes.Structure):
        _fields_ = [
            ("memory_type_count", ctypes.c_uint32),
            ("memory_types", VkMemoryType * 32),
            ("memory_heap_count", ctypes.c_uint32),
            ("memory_heaps", VkMemoryHeap * 16),
        ]

    lib.vkGetPhysicalDeviceMemoryProperties.restype = None
    lib.vkGetPhysicalDeviceMemoryProperties.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(VkPhysicalDeviceMemoryProperties),
    ]

    props = VkPhysicalDeviceMemoryProperties()
    lib.vkGetPhysicalDeviceMemoryProperties(device, ctypes.byref(props))

    total = 0
    for i in range(props.memory_heap_count):
        heap = props.memory_heaps[i]
        if heap.flags & _VK_MEMORY_HEAP_DEVICE_LOCAL_BIT:
            total += heap.size
    return total / (1024**3)


def _from_torch() -> float | None:
    """Fallback: read total VRAM from torch's CUDA device properties."""
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return torch.cuda.get_device_properties(0).total_memory / (1024**3)
    except Exception:
        return None
