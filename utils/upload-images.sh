#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./utils/upload-images.sh <image-directory> [options]

Options:
  --profile PROFILE   Databricks CLI profile (optional)
  --catalog NAME      Unity Catalog catalog (default: $DEMO_CATALOG or multimodal_demo)
  --schema NAME       Unity Catalog schema (default: $DEMO_SCHEMA or manufacturing)
  --volume NAME       Unity Catalog volume (default: $DEMO_VOLUME or inspection_dropzone)
  -h, --help           Show this help

Examples:
  ./utils/upload-images.sh ./sample-images
  ./utils/upload-images.sh ./sample-images --profile DEFAULT
  ./utils/upload-images.sh ./wave1 --catalog multimodal_demo --schema manufacturing --volume inspection_dropzone

The script uploads only .png, .jpg, and .jpeg files. It never deletes files.
EOF
}

[[ $# -ge 1 ]] || { usage >&2; exit 2; }
[[ "${1:-}" != "-h" && "${1:-}" != "--help" ]] || { usage; exit 0; }

SOURCE_DIR=$1
shift

CATALOG=${DEMO_CATALOG:-multimodal_demo}
SCHEMA=${DEMO_SCHEMA:-manufacturing}
VOLUME=${DEMO_VOLUME:-inspection_dropzone}
PROFILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) [[ $# -ge 2 ]] || { echo "Missing value for --profile" >&2; exit 2; }; PROFILE=$2; shift 2 ;;
    --catalog) [[ $# -ge 2 ]] || { echo "Missing value for --catalog" >&2; exit 2; }; CATALOG=$2; shift 2 ;;
    --schema) [[ $# -ge 2 ]] || { echo "Missing value for --schema" >&2; exit 2; }; SCHEMA=$2; shift 2 ;;
    --volume) [[ $# -ge 2 ]] || { echo "Missing value for --volume" >&2; exit 2; }; VOLUME=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -d "$SOURCE_DIR" ]] || { echo "Image directory does not exist: $SOURCE_DIR" >&2; exit 1; }
command -v databricks >/dev/null 2>&1 || { echo "Databricks CLI is not installed or not on PATH." >&2; exit 1; }

DEST="dbfs:/Volumes/${CATALOG}/${SCHEMA}/${VOLUME}"
CLI=(databricks)
[[ -z "$PROFILE" ]] || CLI+=(--profile "$PROFILE")

IMAGES=()
while IFS= read -r -d '' image; do
  IMAGES+=("$image")
done < <(find "$SOURCE_DIR" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) -print0)

if [[ ${#IMAGES[@]} -eq 0 ]]; then
  echo "No .png, .jpg, or .jpeg files found in $SOURCE_DIR" >&2
  exit 1
fi

echo "Uploading ${#IMAGES[@]} image(s) to ${DEST}/"
for image in "${IMAGES[@]}"; do
  filename=$(basename "$image")
  echo "  -> $filename"
  "${CLI[@]}" fs cp "$image" "${DEST}/${filename}" --overwrite
done

echo "Done. No files were deleted from the drop zone."
