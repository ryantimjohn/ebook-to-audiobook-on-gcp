# -*- coding: utf-8 -*-
"""
Cloud-Based Ebook to Audiobook Conversion Pipeline

Description:
This script orchestrates the conversion of an ebook library on a GCP VM.
"""
import os
import sys
import json
import shutil
import argparse
import subprocess
import requests
from io import BytesIO

# Third-party libraries
from googleapiclient.discovery import build
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

# --- Local Imports ---
try:
    from manual_exclusion_list import MANUAL_EXCLUSION_LIST
except ImportError:
    print(
        "⚠️ WARNING: 'manual_exclusion_list.py' not found. Creating an empty exclusion list."
    )
    MANUAL_EXCLUSION_LIST = set()
try:
    from language_map import LANGUAGE_MAP
except ImportError:
    print("⚠️ WARNING: 'language_map.py' not found. Creating an empty language map.")
    LANGUAGE_MAP = {}
try:
    from language_codes_available_to_vits import LANGUAGE_CODES_AVAILABLE_TO_VITS
except ImportError:
    print(
        "⚠️ WARNING: 'language_codes_available_to_vits.py' not found. Creating an empty language codes available to vits."
    )
    LANGUAGE_CODES_AVAILABLE_TO_VITS = set()

# --- Configuration ---
GCP_CONFIG_FILE = "gcp_config.json"
SETUP_SCRIPT_NAME = "setup_remote.sh"
GCP_CONFIG = {}
TEMP_INPUT_DIR = "tmp_input"
TEMP_OUTPUT_DIR = "tmp_output"
STDOUT_LOG_FILE = "stdout.txt"
STDERR_LOG_FILE = "stderr.txt"
FILE_FORMAT_PRIORITY = [".epub", ".azw3", ".azw", ".mobi", ".txt", ".pdf"]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
}


# --- Cloud Interaction Functions ---
def run_gcloud_command(args, check=False, stream_output=False):
    is_windows = sys.platform.startswith("win")
    try:
        command_list = ["gcloud", "compute"] + args
        command_to_run = " ".join(command_list) if is_windows else command_list
        print(f"   > Executing: {command_to_run}")
        if stream_output:
            # For streaming, we don't capture output, so it goes to the console.
            result = subprocess.run(command_to_run, check=check, shell=is_windows)
        else:
            result = subprocess.run(
                command_to_run,
                check=check,
                capture_output=True,
                text=True,
                shell=is_windows,
            )
        return result
    except FileNotFoundError:
        print("❌ ERROR: 'gcloud' command not found.")
        return None
    except subprocess.CalledProcessError as e:
        if check and not stream_output:
            print(f"   ❌ ERROR: gcloud command failed. Stderr:\n{e.stderr}")
        return e


def upload_to_vm(local_path, remote_path, book_info=None):
    print(f"   ↗️   Uploading '{os.path.basename(local_path)}' to VM...")
    full_remote_path = (
        f"{GCP_CONFIG['REMOTE_USER']}@{GCP_CONFIG['INSTANCE_NAME']}:{remote_path}"
    )
    args = [
        "scp",
        "--zone",
        GCP_CONFIG["GCP_ZONE"],
        "--recurse",
        local_path,
        full_remote_path,
    ]
    result = run_gcloud_command(args, check=True, stream_output=True)
    return result is not None and result.returncode == 0


def download_from_vm(remote_path, local_path, book_info=None):
    print(f"   ↙️   Downloading results from VM...")
    full_remote_path = (
        f"{GCP_CONFIG['REMOTE_USER']}@{GCP_CONFIG['INSTANCE_NAME']}:{remote_path}"
    )
    args = [
        "scp",
        "--zone",
        GCP_CONFIG["GCP_ZONE"],
        "--recurse",
        full_remote_path,
        local_path,
    ]
    result = run_gcloud_command(args, check=True, stream_output=True)
    return result is not None and result.returncode == 0


def run_remote_command(command_str, timeout=None, book_info=None):
    print(f"   ☁️   Executing remote command: {command_str}")
    if timeout:
        command_str = f"timeout {timeout}s {command_str}"

    ssh_args = [
        "ssh",
        f"{GCP_CONFIG['REMOTE_USER']}@{GCP_CONFIG['INSTANCE_NAME']}",
        "--zone",
        GCP_CONFIG["GCP_ZONE"],
        "--",
        command_str,
    ]
    return run_command_with_realtime_logging(
        ["gcloud", "compute"] + ssh_args, book_info=book_info
    )


def run_command_with_realtime_logging(command, book_info=None):
    is_windows = sys.platform.startswith("win")
    command_to_run = " ".join(command) if is_windows else command
    print(f"    > Running: {command_to_run}")
    try:
        with open(STDOUT_LOG_FILE, "a", encoding="utf-8") as f_out, open(
            STDERR_LOG_FILE, "a", encoding="utf-8"
        ) as f_err:
            process = subprocess.Popen(
                command_to_run,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                universal_newlines=True,
                shell=is_windows,
            )
            if book_info:
                prefix = f"[{book_info['current_book']}/{book_info['total_books']}] {book_info['book_title']} "
            else:
                prefix = "[REMOTE] "

            for line in iter(process.stdout.readline, ""):
                sys.stdout.write(prefix + line)
                f_out.write(line)
            for line in iter(process.stderr.readline, ""):
                sys.stderr.write(prefix + "[ERR] " + line)
                f_err.write(line)
            return_code = process.wait()
            return return_code == 0
    except Exception as e:
        print(f"   ❌ An unexpected error occurred: {e}")
        return False


def setup_remote_vm(git_repo, git_branch, git_repo_name, force_rebuild):
    """Uploads and executes the setup script on the remote VM."""
    print("--- Starting Remote VM Setup ---")
    remote_home = f"/home/{GCP_CONFIG['REMOTE_USER']}"
    remote_script_path = f"{remote_home}/{SETUP_SCRIPT_NAME}"

    print("\nStep 1/3: Uploading setup script...")
    if not upload_to_vm(SETUP_SCRIPT_NAME, remote_home):
        print("❌ CRITICAL: Failed to upload setup script. Exiting.")
        return False

    print("\nStep 2/3: Making remote script executable...")
    if not run_remote_command(f"chmod +x {remote_script_path}"):
        print("❌ CRITICAL: Failed to make setup script executable. Exiting.")
        return False

    print("\nStep 3/3: Executing remote setup script...")
    force_rebuild_arg = str(force_rebuild).lower()
    if not run_remote_command(
        f'bash {remote_script_path} "{git_repo}" "{git_branch}" "{git_repo_name}" "{force_rebuild_arg}"'
    ):
        print("❌ CRITICAL: Failed to execute setup script. Exiting.")
        return False

    print("\n✅ Remote VM setup appears successful.")
    return True


# --- Main Logic and Utility Functions ---


def get_google_search_creds():
    try:
        with open("api_key.txt", "r") as f:
            api_key = f.read().strip()
        with open("search_engine_id.txt", "r") as f:
            search_engine_id = f.read().strip()
        return api_key, search_engine_id
    except (FileNotFoundError, ValueError):
        return None, None


def find_cover_image_url(folder_name, api_key, search_engine_id):
    query_formats = [
        '"{}" book cover',  # Exact phrase + "book cover"
        '"{}"',  # Exact phrase
        "{} book cover",  # Broad search + "book cover"
        "{}",  # Broadest search
    ]
    image_sizes = ["XLARGE", "LARGE", "MEDIUM", "SMALL"]

    for q_format in query_formats:
        for size in image_sizes:
            query = q_format.format(folder_name)
            print(f"    - Searching... (Query: {query}, Size: {size})")

            api_results = None
            try:
                service = build("customsearch", "v1", developerKey=api_key)
                api_results = (
                    service.cse()
                    .list(
                        q=query,
                        cx=search_engine_id,
                        searchType="image",
                        num=3,
                        imgSize=size,
                        safe="off",
                    )
                    .execute()
                )

            except HttpError as e:
                reason = f"API Error on query '{query}': {e}"
                if e.resp.status == 403:
                    reason += " (This may be a daily quota limit issue. Check your Google Cloud Console.)"
                return False, reason  # A hard API error should stop immediately
            except Exception as e:
                return False, f"Unexpected API call error: {e}"

            # If we got results, try to download them
            if api_results and "items" in api_results and api_results["items"]:
                for i, item in enumerate(api_results["items"]):
                    try:
                        image_url = item["link"]
                        print(
                            f"    - Attempting download [{i+1}/{len(api_results['items'])}]: {image_url[:80]}..."
                        )

                        image_response = requests.get(
                            image_url, stream=True, headers=HTTP_HEADERS, timeout=6
                        )
                        image_response.raise_for_status()

                        return image_url  # Found and downloaded, we are done.

                    except requests.exceptions.RequestException as e:
                        print(
                            f"    - Note: Download error for URL [{i+1}] ({type(e).__name__}). Trying next image..."
                        )
                        continue  # Try the next image link

                print("    - Note: All image links for this search failed to download.")

    # If all queries and sizes have been tried and failed
    return False, "No results found after all search attempts."


def embed_cover_image(m4b_path, image_url):
    if not image_url:
        return False
    try:
        print(f"🖼️ Embedding cover into: {os.path.basename(m4b_path)}")
        response = requests.get(image_url, stream=True)
        response.raise_for_status()
        image_data = BytesIO(response.content)
        img = Image.open(image_data)
        image_format = (
            MP4Cover.FORMAT_JPEG
            if img.format.lower() == "jpeg"
            else MP4Cover.FORMAT_PNG
        )
        audio = MP4(m4b_path)
        audio["covr"] = [MP4Cover(image_data.getvalue(), imageformat=image_format)]
        audio.save()
        return True
    except Exception as e:
        print(f"   ❌ ERROR embedding cover: {e}")
        return False


def update_m4b_metadata(m4b_path, title):
    try:
        print(f"✍️ Updating metadata title to: '{title}'")
        audio = MP4(m4b_path)
        audio["\xa9nam"] = [title]
        audio.save()
        return True
    except Exception as e:
        print(f"   ❌ ERROR updating metadata: {e}")
        return False


def find_best_ebook_file(folder_path):
    for ext in FILE_FORMAT_PRIORITY:
        for file in os.listdir(folder_path):
            if file.lower().endswith(ext):
                return os.path.join(folder_path, file)
    return None


def setup_temp_dirs():
    for temp_dir in [TEMP_INPUT_DIR, TEMP_OUTPUT_DIR]:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
    print(f"✅ Local temporary directories are ready.")


def post_process_files(wsl_output_dir, book, audiobooks_root, book_info=None):
    print("   -> Starting local post-processing...")
    files_location = os.path.join(wsl_output_dir, "output")
    output_files = [f for f in os.listdir(files_location) if f.lower().endswith(".m4b")]
    if not output_files:
        print(
            "   ❌ ERROR: No M4B file found in downloaded output. Check remote logs for errors."
        )
        return

    original_m4b_path = os.path.join(files_location, output_files[0])
    new_book_name = f"{book['name']} TTS"
    new_filename = f"{new_book_name}.m4b"
    final_dir = os.path.join(
        audiobooks_root, os.path.dirname(book["relative_path"]), book["name"] + " TTS"
    )
    os.makedirs(final_dir, exist_ok=True)
    temp_renamed_path = os.path.join(TEMP_OUTPUT_DIR, new_filename)
    shutil.move(original_m4b_path, temp_renamed_path)
    api_key, se_id = get_google_search_creds()
    if api_key:
        update_m4b_metadata(temp_renamed_path, new_book_name)
        cover_url = find_cover_image_url(book["name"], api_key, se_id)
        embed_cover_image(temp_renamed_path, cover_url)
    final_path = os.path.join(final_dir, new_filename)
    shutil.move(temp_renamed_path, final_path)
    print(f"\n   ✅ Successfully created audiobook: {final_path}")


def scan_for_books(ebooks_root, audiobooks_root, monolingual_code=None):
    """
    Scans the ebook library for items to convert.
    Supports both multilingual (directory-based) and monolingual libraries.
    """
    books_to_convert = []
    auto_exclude_list = {
        d[:-4].lower() if d.endswith(" TTS") else d.lower()
        for r, ds, _ in os.walk(audiobooks_root)
        for d in ds
    }

    if monolingual_code:
        print(f"📚 Scanning in monolingual mode for language: {monolingual_code}")
        # Walk through all directories to find potential book folders
        for root, dirs, _ in os.walk(ebooks_root):
            # Create a copy of dirs to modify it while iterating
            for book_dir in list(dirs):
                book_path = os.path.join(root, book_dir)
                best_file = find_best_ebook_file(book_path)
                if best_file:
                    # This directory contains an ebook, treat it as a book
                    unique_path = os.path.relpath(book_path, ebooks_root).replace(
                        "\\", "/"
                    )
                    if (
                        book_dir.lower() not in auto_exclude_list
                        and unique_path not in MANUAL_EXCLUSION_LIST
                    ):
                        books_to_convert.append(
                            {
                                "path": best_file,
                                "name": book_dir,
                                "lang_code": monolingual_code,
                                "relative_path": unique_path,
                            }
                        )
                    # We've processed this directory as a book, so don't traverse into it
                    dirs.remove(book_dir)
    else:
        print("📚 Scanning in multilingual mode (language-based directories)...")
        for lang_dir in os.listdir(ebooks_root):
            lang_path = os.path.join(ebooks_root, lang_dir)
            if not os.path.isdir(lang_path):
                continue
            for category_dir in os.listdir(lang_path):
                category_path = os.path.join(lang_path, category_dir)
                if not os.path.isdir(category_path):
                    continue
                for book_dir in os.listdir(category_path):
                    book_path = os.path.join(category_path, book_dir)
                    if not os.path.isdir(book_path):
                        continue
                    unique_path = os.path.join(
                        lang_dir, category_dir, book_dir
                    ).replace("\\", "/")
                    if (
                        book_dir.lower() not in auto_exclude_list
                        and unique_path not in MANUAL_EXCLUSION_LIST
                    ):
                        best_file = find_best_ebook_file(book_path)
                        if best_file:
                            books_to_convert.append(
                                {
                                    "path": best_file,
                                    "name": book_dir,
                                    "lang_code": LANGUAGE_MAP.get(
                                        lang_dir.lower(), "en"
                                    ),
                                    "relative_path": os.path.relpath(
                                        book_path, ebooks_root
                                    ),
                                }
                            )
    return books_to_convert


def main(
    ebooks_root,
    audiobooks_root,
    git_repo="https://github.com/ryantimjohn/ebook2audiobook.git",
    git_branch="main",
    force_rebuild=False,
    num_threads=10,
    monolingual_code=None,
):
    global GCP_CONFIG
    git_repo_name = (
        git_repo.replace("https://github.com/", "")
        .replace(".git", "")
        .replace("/", "-")
    )
    try:
        with open(GCP_CONFIG_FILE, "r") as f:
            GCP_CONFIG = json.load(f)
        print(f"✅ Loaded configuration from '{GCP_CONFIG_FILE}'.")
    except FileNotFoundError:
        print(f"❌ CRITICAL ERROR: Config file '{GCP_CONFIG_FILE}' not found.")
        sys.exit(1)

    if not os.path.exists(SETUP_SCRIPT_NAME):
        print(f"❌ CRITICAL ERROR: Setup script '{SETUP_SCRIPT_NAME}' not found.")
        sys.exit(1)

    if not setup_remote_vm(git_repo, git_branch, git_repo_name, force_rebuild):
        sys.exit(1)

    books_to_convert = scan_for_books(ebooks_root, audiobooks_root, monolingual_code)

    print(f"\nFound {len(books_to_convert)} new books to convert.")
    for i, book in enumerate(books_to_convert):
        print("\n" + "=" * 80)
        print(f"🔄 Processing book {i+1}/{len(books_to_convert)}: {book['name']}")
        print("=" * 80)
        book_info = {
            "book_title": book["name"],
            "current_book": i + 1,
            "total_books": len(books_to_convert),
        }
        setup_temp_dirs()
        try:
            remote_home = f"/home/{GCP_CONFIG['REMOTE_USER']}"
            remote_input_dir = f"{remote_home}/input"
            remote_output_dir = f"{remote_home}/output"
            wsl_output_dir = f"/home/{GCP_CONFIG['REMOTE_USER']}/tmp"

            if not run_remote_command(
                f"mkdir -p {remote_input_dir} {remote_output_dir}",
                timeout=60,
                book_info=book_info,
            ):
                continue
            if not upload_to_vm(book["path"], remote_input_dir, book_info=book_info):
                continue
            input_filename = os.path.basename(book["path"])
            safe_filename = input_filename.replace('"', '\\"')

            custom_docker_image_name = (
                f"ebook-converter-custom:{git_repo_name}-{git_branch}"
            )
            docker_base_command = (
                f"docker run --rm --gpus all "
                f"-v {remote_input_dir}:/app/input -v {remote_output_dir}:/app/output "
                f"-v {remote_home}/models:/app/models "
                f"{custom_docker_image_name} --headless --device gpu "
                f'--ebook "/app/input/{safe_filename}" --output_dir /app/output '
                f"--language {book['lang_code']} --output_format m4b "
                f"--tts_engine {'vits' if book['lang_code'] in LANGUAGE_CODES_AVAILABLE_TO_VITS else 'fairseq'} "
                f"--num_workers {num_threads}"
            )

            docker_command = f"{docker_base_command}"

            if not run_remote_command(
                docker_command, timeout=3600, book_info=book_info
            ):
                print(
                    f"   ⚠️ Remote command failed for {book['name']}. Skipping to next book."
                )
                continue

            download_message = download_from_vm(
                remote_output_dir, wsl_output_dir, book_info=book_info
            )
            print(download_message)
            if not download_message:
                print(
                    f"   ⚠️ Download failed for {book['name']}. Retrying... in 15 seconds. {counter} attempts left."
                )
                continue

            post_process_files(
                wsl_output_dir, book, audiobooks_root, book_info=book_info
            )
            shutil.rmtree(os.path.join(wsl_output_dir, "output"))

        except KeyboardInterrupt:
            print("\n\n🛑 KeyboardInterrupt detected. Stopping script.")
            sys.exit(1)
        except Exception as e:
            print(f"   ❌ An unexpected error occurred for {book['name']}: {e}")
        finally:
            print("   -> Cleaning up remote directories...")
            run_remote_command(
                f"rm -rf {remote_home}/input {remote_home}/output", timeout=60
            )

    print("\n\n🎉🎉🎉 All books processed. Conversion pipeline finished! 🎉🎉🎉")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cloud-based script to convert an ebook library to audiobooks."
    )
    parser.add_argument(
        "ebooks_dir", help="The root directory of your local ebook library."
    )
    parser.add_argument(
        "audiobooks_dir",
        help="The root directory where final audiobooks will be saved.",
    )
    parser.add_argument(
        "-g",
        "--git-repo",
        dest="git_repo",
        default="https://github.com/ryantimjohn/ebook2audiobook.git",
        help="The git repository to use for the Docker image and setup.",
    )
    parser.add_argument(
        "-b",
        "--git-branch",
        dest="git_branch",
        default="main",
        help="The git branch to use for the Docker image and setup.",
    )
    parser.add_argument(
        "-r",
        "--force-docker-image-rebuild",
        dest="force_docker_image_rebuild",
        action="store_true",
        help="Force a rebuild of the remote Docker image.",
    )
    parser.add_argument(
        "-t",
        "--num-threads",
        dest="num_threads",
        default=10,
        type=int,
        help="The number of threads to use for the Docker image and setup.",
    )
    parser.add_argument(
        "-m",
        "--monolingual",
        dest="monolingual_code",
        default=None,
        type=str,
        help="Process the library in monolingual mode with the given 3-letter language code (e.g., 'eng').",
    )
    args = parser.parse_args()
    if not os.path.isdir(args.ebooks_dir) or not os.path.isdir(args.audiobooks_dir):
        print("Error: Ebook or Audiobook directory not found.")
        sys.exit(1)
    main(
        args.ebooks_dir,
        args.audiobooks_dir,
        args.git_repo,
        args.git_branch,
        args.force_docker_image_rebuild,
        args.num_threads,
        args.monolingual_code,
    )
