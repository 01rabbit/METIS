#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 NEW_BUILD_DIRECTORY" >&2
    exit 2
fi
if [ -e "$1" ]; then
    echo "Build directory must not already exist." >&2
    exit 2
fi
for command in git cmake python3; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required build tool is unavailable: $command" >&2
        exit 2
    fi
done
if ! python3 -I -c 'import sys; raise SystemExit(sys.version_info < (3, 12))'; then
    echo "Python 3.12 or newer is required to write the trace manifest." >&2
    exit 2
fi

case "$(uname -s):$(uname -m)" in
    Darwin:arm64|Linux:aarch64|Linux:x86_64) ;;
    *)
        echo "Trace build supports Darwin arm64 and Linux arm64/x86_64 only." >&2
        exit 2
        ;;
esac

metis_repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
metis_source_pin=b1b770d90d94cad9e9ea5b993bdbc383a522fb28
metis_source_remote=${METIS_LLAMA_SOURCE_REMOTE:-https://github.com/ggml-org/llama.cpp.git}
metis_build_jobs=${METIS_LLAMA_BUILD_JOBS:-4}
case "$metis_build_jobs" in
    ''|*[!0-9]*) echo "METIS_LLAMA_BUILD_JOBS must be a positive integer." >&2; exit 2 ;;
esac
if [ "$metis_build_jobs" -lt 1 ] || [ "$metis_build_jobs" -gt 32 ]; then
    echo "METIS_LLAMA_BUILD_JOBS must be between 1 and 32." >&2
    exit 2
fi

mkdir -- "$1"
metis_build_root=$(CDPATH='' cd -- "$1" && pwd)
cp -- "$metis_repo_root/integrations/llama-server-work-trace/llama-work-trace.patch" \
    "$metis_build_root/llama-work-trace.patch"
chmod a-w "$metis_build_root/llama-work-trace.patch"

# Always fetch the exact commit into a fresh tree; a local mirror can be supplied
# through METIS_LLAMA_SOURCE_REMOTE to keep an offline reproduction self-contained.
git init "$metis_build_root/source"
git -C "$metis_build_root/source" fetch --depth=1 "$metis_source_remote" "$metis_source_pin"
git -C "$metis_build_root/source" checkout --detach "$metis_source_pin"
test "$(git -C "$metis_build_root/source" rev-parse HEAD)" = "$metis_source_pin"
git -C "$metis_build_root/source" apply --check --whitespace=error \
    "$metis_build_root/llama-work-trace.patch"
git -C "$metis_build_root/source" apply --whitespace=error \
    "$metis_build_root/llama-work-trace.patch"

cmake -S "$metis_build_root/source" -B "$metis_build_root/build" \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    -DGGML_BACKEND_DL=OFF -DGGML_METAL=OFF -DGGML_BLAS=OFF \
    -DGGML_OPENMP=OFF -DGGML_NATIVE=OFF \
    -DLLAMA_BUILD_APP=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF \
    -DLLAMA_SUBPROCESS=OFF -DLLAMA_OPENSSL=OFF
cmake --build "$metis_build_root/build" --target llama-server --parallel "$metis_build_jobs"
python3 -I "$metis_repo_root/scripts/write_llama_work_trace_manifest.py" "$metis_build_root"
printf '%s\n' "$metis_build_root/build/bin/llama-server"
