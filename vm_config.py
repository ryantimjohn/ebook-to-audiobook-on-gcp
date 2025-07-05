# I've found that the L4 GPU is the best for this use case.
VM_CONFIG = {
    "machine_type": "g2-standard-32",
    "gpu_type": "nvidia-l4",
    "gpu_metric_name": "NVIDIA_L4_GPUS",
    "image_family": "pytorch-latest-cu124-debian-11",
    "image_project": "deeplearning-platform-release",
    "disk_size": "200GB",
    "scopes": "https://www.googleapis.com/auth/cloud-platform",
    "maintenance_policy": "TERMINATE",
}
