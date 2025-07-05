#!/bin/bash

# This script is designed to be run on the remote GCP Deep Learning VM.
# It handles the one-time setup of the ebook2audiobook environment.

set -e # Exit immediately if a command exits with a non-zero status.

# The first argument is the git repository, defaulting to 'https://github.com/ryantimjohn/ebook2audiobook.git' if not provided
GIT_REPO=${1:-https://github.com/ryantimjohn/ebook2audiobook.git}
# The second argument is the git branch, defaulting to 'main' if not provided
GIT_BRANCH=${2:-main}
# The third argument is the git repository name, defaulting to 'ryantimjohn-ebook2audiobook' if not provided
GIT_REPO_NAME=${3:-ryantimjohn-ebook2audiobook}
# The fourth argument is a flag to force Docker image rebuild
FORCE_REBUILD=${4:-false}

REMOTE_REPO_PATH="~/${GIT_REPO_NAME}"
CUSTOM_DOCKER_IMAGE_NAME="ebook-converter-custom:${GIT_REPO_NAME}-${GIT_BRANCH}"
BASE_DOCKER_IMAGE="athomasson2/ebook2audiobook"

# Resolve the tilde to the absolute home directory path
EVAL_REMOTE_REPO_PATH=$(eval echo "$REMOTE_REPO_PATH")

echo GIT_REPO_NAME: $GIT_REPO_NAME
echo REMOTE_REPO_PATH: $REMOTE_REPO_PATH
echo CUSTOM_DOCKER_IMAGE_NAME: $CUSTOM_DOCKER_IMAGE_NAME
echo BASE_DOCKER_IMAGE: $BASE_DOCKER_IMAGE
echo EVAL_REMOTE_REPO_PATH: $EVAL_REMOTE_REPO_PATH

echo "--- Starting One-Time Remote VM Setup ---"

# 1. Check for and clone the repository
echo "Step 1/3: Checking for remote repository at ${EVAL_REMOTE_REPO_PATH}..."
if [ ! -d "$EVAL_REMOTE_REPO_PATH" ]; then
    echo "  -> Repository not found. Cloning..."
    git clone "$GIT_REPO" "$EVAL_REMOTE_REPO_PATH"
    cd "$EVAL_REMOTE_REPO_PATH"
    git checkout "$GIT_BRANCH"
    cd ..
else
    echo "  -> Repository already exists. Skipping clone."
fi

# 2. Check for and build the custom Docker image
echo ""
echo "Step 2/3: Checking for custom Docker image: ${CUSTOM_DOCKER_IMAGE_NAME}..."
# Check if a build is needed (either image is missing or a force rebuild is requested)
if [[ "$(docker images -q "${CUSTOM_DOCKER_IMAGE_NAME}" 2> /dev/null)" == "" ]] || [ "$FORCE_REBUILD" = "true" ]; then
  if [ "$FORCE_REBUILD" = "true" ]; then
    echo "  -> Force rebuild requested. Building image..."
  else
    echo "  -> Custom Docker image not found. Building... (This may take 15-30 minutes)"
  fi
  cd "$EVAL_REMOTE_REPO_PATH"
  git fetch
  git checkout "$GIT_BRANCH"
  git pull
  docker build -t "$CUSTOM_DOCKER_IMAGE_NAME" --build-arg TORCH_VERSION=cuda124 .
else
  echo "  -> Custom Docker image already exists. Skipping build."
fi

# 3. Pre-pull the base image to ensure it is up to date
echo ""
echo "Step 3/3: Pre-pulling the base image to ensure it's up to date..."
docker pull "$BASE_DOCKER_IMAGE"

echo ""
echo "✅ Remote VM setup is complete."
echo "--- End of Remote VM Setup ---"

