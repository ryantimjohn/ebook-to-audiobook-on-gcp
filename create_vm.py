# -*- coding: utf-8 -*-
"""
Intelligent Python Script to Find and Create a GCP VM.

If it succeeds, it saves the connection details to a JSON config file.

Prerequisites:
- Python 3.7+
- Google Cloud SDK (`gcloud` CLI) installed and configured.

Usage:
1. Ensure you are authenticated with the gcloud CLI by running 'gcloud init'.
2. Run the script from your terminal:
   python find_and_create_vm.py --instance-name "ebook-converter-vm"
"""
import subprocess
import json
import sys
import argparse
from vm_config import VM_CONFIG


def run_gcloud_command(args, capture_output=True):
    """Executes a gcloud command and returns the result."""
    is_windows = sys.platform.startswith("win")
    try:
        command_list = ["gcloud"] + args
        # For Windows, we need to use shell=True and pass the command as a string
        command_to_run = " ".join(command_list) if is_windows else command_list

        process = subprocess.run(
            command_to_run,
            capture_output=capture_output,
            text=True,
            check=True,  # This will raise a CalledProcessError if the command fails
            shell=is_windows,  # Crucial fix for Windows PATH issues
        )
        return process
    except FileNotFoundError:
        print(
            "❌ ERROR: 'gcloud' command not found. Is the Google Cloud SDK installed and in your system's PATH?"
        )
        return None
    except subprocess.CalledProcessError as e:
        # Return the error object so the calling function can inspect stderr
        return e


def get_gcp_details():
    """Fetches the current GCP project ID and authenticated user email."""
    try:
        project_id_proc = run_gcloud_command(["config", "get-value", "project"])
        project_id = project_id_proc.stdout.strip()

        user_email_proc = run_gcloud_command(
            ["auth", "list", "--filter=status:ACTIVE", "--format=value(account)"]
        )
        user_email = user_email_proc.stdout.strip().split("\n")[
            0
        ]  # Get the first active account

        if not project_id or not user_email:
            raise ValueError("Could not retrieve project ID or user email.")

        remote_user = user_email.split("@")[0].replace(".", "_")
        return project_id, remote_user
    except (ValueError, IndexError, AttributeError):
        print(
            f"❌ ERROR: Could not get GCP details. Please run 'gcloud init' and 'gcloud auth login'."
        )
        return None, None


def main(instance_name, config_filename):
    """Main function to find a zone and create the VM."""
    project_id, remote_user = get_gcp_details()
    if not project_id:
        sys.exit(1)

    print("Fetching list of all available GCP zones...")
    zones_proc = run_gcloud_command(
        ["compute", "zones", "list", "--format=value(name)"]
    )
    if not zones_proc or zones_proc.returncode != 0:
        print("❌ ERROR: Failed to fetch zones list.")
        sys.exit(1)

    zones = zones_proc.stdout.strip().split("\n")
    print(
        f"Found {len(zones)} zones. Starting search for available resources in project '{project_id}'."
    )
    print(
        f"Attempting to create a '{VM_CONFIG['machine_type']}' instance with a '{VM_CONFIG['gpu_type']}' GPU."
    )

    vm_created = False
    successful_zone = ""

    for zone in zones:
        print("-" * 60)
        print(f"Attempting to create VM in zone: '{zone}'...")

        command_args = [
            "compute",
            "instances",
            "create",
            instance_name,
            "--project",
            project_id,
            "--zone",
            zone,
            "--machine-type",
            VM_CONFIG["machine_type"],
            "--accelerator",
            f"type={VM_CONFIG['gpu_type']},count=1",
            "--image-family",
            VM_CONFIG["image_family"],
            "--image-project",
            VM_CONFIG["image_project"],
            "--boot-disk-size",
            VM_CONFIG["disk_size"],
            "--scopes",
            VM_CONFIG["scopes"],
            "--maintenance-policy",
            VM_CONFIG["maintenance_policy"],
            "--format=json",
        ]

        result = run_gcloud_command(command_args)

        if result and result.returncode == 0:
            print(
                f"✅ SUCCESS! VM '{instance_name}' created successfully in zone '{zone}'."
            )
            vm_created = True
            successful_zone = zone
            break
        else:
            error_message = result.stderr if result else "Unknown error."
            if "QUOTA_EXCEEDED" in error_message:
                print(
                    f"❌ QUOTA EXCEEDED in zone '{zone}'. Your project is not allowed to create this type of GPU."
                )
                region = "-".join(zone.split("-")[:2])
                metric_name = VM_CONFIG["gpu_metric_name"]
                quota_url = (
                    f"https://console.cloud.google.com/iam-admin/quotas?project={project_id}"
                    f"&pageState=(%22allQuotas%22:(%22hidden%22:true,%22metric%22:%22compute.googleapis.com%2F"
                    f"{metric_name}%22,%22region%22:%22{region}%22))&cloudshell=false"
                )

                print("\n" + "-" * 29 + " ACTION REQUIRED " + "-" * 29)
                print(
                    f"You must request a quota increase for '{VM_CONFIG['gpu_type']}' GPUs in the '{region}' region."
                )
                print(
                    "1. Click the link below to go directly to the quota request page."
                )
                print("2. Check the box for the quota, click 'EDIT QUOTAS'.")
                print("3. Set the new limit to '1' and submit the request.")
                print(
                    "4. After Google approves your request via email, run this script again."
                )
                print(f"\nDirect Link: {quota_url}\n")
                print("-" * 75)
                sys.exit(1)
            elif "ZONE_RESOURCE_POOL_EXHAUSTED" in error_message:
                print(f"⚠️ Resource unavailable in zone '{zone}'. Trying next zone.")
            else:
                print(
                    f"⚠️ Failed to create VM in '{zone}'. The error from gcloud was:\n{error_message}"
                )

    if vm_created:
        print("-" * 60)
        print("VM created. Generating configuration file...")
        config_data = {
            "GCP_PROJECT_ID": project_id,
            "GCP_ZONE": successful_zone,
            "INSTANCE_NAME": instance_name,
            "REMOTE_USER": remote_user,
        }
        with open(config_filename, "w") as f:
            json.dump(config_data, f, indent=4)
        print(f"✅ Configuration file '{config_filename}' created successfully:")
        print(json.dumps(config_data, indent=4))
    else:
        print(
            "❌ Could not create the VM in any of the available zones. This may be due to temporary resource unavailability across all zones. Please try again later."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Finds and creates a GPU-enabled VM on GCP."
    )
    parser.add_argument(
        "--instance-name",
        default="ebook-converter-vm",
        help="The name for the new virtual machine.",
    )
    parser.add_argument(
        "--config-file",
        default="gcp_config.json",
        help="The name of the JSON output file.",
    )
    args = parser.parse_args()

    main(args.instance_name, args.config_file)
