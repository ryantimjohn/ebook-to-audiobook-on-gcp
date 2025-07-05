# Ebook to Audiobook Cloud Conversion Pipeline

This project uses the amazing ebook2audiobook project https://github.com/DrewThomasson/ebook2audiobook to perform ebook TTS conversion on a GPU-accelerated virtual machine, and then downloads the final audiobooks back to your local machine.

## Features

- **Automated Bulk Conversion**: Process an entire library of ebooks with a single command.
- **High-Quality TTS**: Utilizes a powerful TTS engine running in a Docker container on a GCP VM.
- **Multilingual & Monolingual Support**: 
    - **Multilingual**: Automatically detects the language from your directory structure (e.g., `Ebooks/English/...`).
    - **Monolingual**: Can process an entire library as a single language, regardless of the directory structure.
- **Resumable**: The pipeline automatically skips books that have already been converted, so you can safely restart it.
- **Cover Art & Metadata**: Fetches book covers using Google Custom Search and embeds the cover, title, and author into the final `m4b` audiobook file.
- **Detailed Logging**: Provides real-time progress updates for VM setup, file transfers, and each book's conversion status.

---

## Prerequisites

Before you begin, you will need to install the required software and set up your Google Cloud environment.

### 1. Software to Install

- **Python 3.8+**: Make sure you have a modern version of Python installed. You can download it from [python.org](https://www.python.org/).
- **Google Cloud SDK**: This provides the `gcloud` command-line tool used to interact with your GCP resources. Follow the [official installation guide](https://cloud.google.com/sdk/docs/install).

### 2. Google Cloud Platform (GCP) Setup

1.  **Create a GCP Project**: If you don't have one already, create a new project in the [GCP Console](https://console.cloud.google.com/).
2.  **Enable Billing**: Ensure that billing is enabled for your project.
3.  **Enable APIs**: You must enable the following APIs for your project:
    - **Compute Engine API**: Used to create and manage the virtual machine.
    - **Custom Search API**: Used to fetch cover art for the audiobooks.
    You can enable them from the "APIs & Services" dashboard in the GCP Console.
4.  **Authenticate the `gcloud` CLI**: Run the following commands in your terminal to log in and set your default project.
    ```bash
    # Log in to your Google account
    gcloud auth login

    # Set up application-default credentials for Python libraries
    gcloud auth application-default login

    # Set your default project ID
    gcloud config set project [YOUR_PROJECT_ID]
    ```
5.  **GPU Quotas**: The script attempts to create a VM with a GPU. New GCP projects often have a GPU quota of 0. You may need to request a quota increase for "GPUs (all regions)" in the "IAM & Admin" -> "Quotas" section of the GCP Console. The `create_vm.py` script will guide you if it detects a quota error.

---

## Project Setup

Follow these steps to configure the project on your local machine.

### 1. Clone the Repository

```bash
# Clone this repository to your local machine
git clone https://github.com/ryantimjohn/ebook-cloud-converter.git

# Navigate into the project directory
cd ebook-cloud-converter
```

### 2. Install Python Dependencies

Install the required Python packages using the included `requirements.txt` file.

```bash
pip install -r requirements.txt
```

### 3. Create Configuration Files

You will need to create a few configuration files. Templates are provided below.


**`api_key.txt` & `search_engine_id.txt` (Required)**
These files store the credentials needed to fetch book covers.

1.  **`api_key.txt`**: Create this file and paste your Google API Key into it. You can get an API key from the GCP Console.

2.  **`search_engine_id.txt`**: Create this file and paste your Programmable Search Engine ID into it. You can create a search engine and get its ID [here](https://programmablesearchengine.google.com/controlpanel/all).

**`manual_exclusion_list.py` (Optional)**
Use this file to manually specify directories that should be skipped during the conversion process. The paths should be relative to your ebooks root directory.

*Create a file named `manual_exclusion_list.py` and add paths to exclude:* 
```python
# manual_exclusion_list.py

MANUAL_EXCLUSION_LIST = [
    "English/Sci-Fi/Some Book I Don't Want",
    "French/History/Another Book to Skip"
]
```

---

## How to Run the Pipeline

### Step 1: Organize Your Ebook Library

The pipeline supports two library structures:

- **Multilingual (Default)**: Organize your books in a `Language/Category/Book Title` structure. The language name will be used to select the correct TTS voice.
    ```
    Ebooks/
    ├── English/
    │   ├── Sci-Fi/
    │   │   └── A Great Book/
    │   │       └── book.epub
    ├── Spanish/
    │   └── Fantasy/
    │       └── Un Gran Libro/
    │           └── libro.azw3
    ```

- **Monolingual**: If your library is all in one language, the structure doesn't matter. The script will find any directory containing an ebook file and process it.
    ```
    Ebooks/
    ├── A Great Book/
    │   └── book.epub
    ├── Another Series/
    │   ├── Book 1/
    │   │   └── book1.kpf
    ```

### Step 2: Create the GCP Virtual Machine

Run the `create_vm.py` script to provision your cloud environment. **You only need to do this once.**

```bash
python create_vm.py --instance-name my-ebook-vm
```
This script will:
1. Create a new GPU-enabled VM using the settings from `vm_config.py`.
2. Wait for the VM to be ready.
3. Create a `gcp_config.json` file in your project directory, which stores the VM's connection details for the main pipeline script.

### Step 3: Run the Conversion Pipeline

Once the VM is running, you can start the conversion process.

**For a multilingual library:**
```bash
python ebook_to_audiobook_cloud_pipeline.py /path/to/your/ebooks /path/to/your/audiobooks
```

**For a monolingual library (e.g., all English books):**
```bash
python ebook_to_audiobook_cloud_pipeline.py /path/to/your/ebooks /path/to/your/audiobooks --monolingual eng
```

The script will then:
1. Set up the remote VM by cloning the TTS repository and building a Docker image.
2. Scan your local ebook library for new books to convert.
3. For each book:
    a. Upload the ebook file to the VM.
    b. Run the TTS conversion inside Docker.
    c. Download the completed `m4b` audiobook.
    d. Fetch cover art, apply metadata, and clean up.

### Command-Line Arguments

- `ebooks_dir`: (Required) The absolute path to your ebook library.
- `audiobooks_dir`: (Required) The absolute path where completed audiobooks will be saved.
- `-m, --monolingual [CODE]`: (Optional) Activates monolingual mode and uses the provided 3-letter language code (e.g., `eng`, `spa`, `fra`).
- `-r,--force-docker-image-rebuild`: (Optional) Forces a rebuild of the Docker image on the VM.
- `-t, --num-threads [N]`: (Optional) Number of threads to use for remote setup. Default is 10.

---

## File Descriptions

- `ebook_to_audiobook_cloud_pipeline.py`: The main orchestrator script that manages the entire workflow.
- `create_vm.py`: A one-time setup script to create the GCP virtual machine.
- `language_map.py`: A dictionary mapping directory-friendly language names (e.g., "english") to 3-letter ISO codes for the TTS engine.
- `vm_config.py`: Defines the hardware and software configuration for the GCP VM.
- `gcp_config.json`: (Auto-generated) Stores the created VM's details for the pipeline to use.
- `api_key.txt`: **(User-created)** Stores your Google API key.
- `search_engine_id.txt`: **(User-created)** Stores your Google Custom Search Engine ID.
- `manual_exclusion_list.py`: **(User-created)** A list of books/directories to explicitly skip.
- `requirements.txt`: A list of the required Python packages for this project.
