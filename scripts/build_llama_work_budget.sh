#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 NEW_BUILD_DIRECTORY" >&2
    exit 2
fi

metis_repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
metis_source_pin=b1b770d90d94cad9e9ea5b993bdbc383a522fb28
mkdir -- "$1"
metis_build_root=$(CDPATH='' cd -- "$1" && pwd)

metis_applied_patch="$metis_build_root/llama-server.patch"
cp -- "$metis_repo_root/integrations/llama-server-work-budget/llama-server.patch" "$metis_applied_patch"
chmod a-w "$metis_applied_patch"

# A fresh tree prevents stale sources, patches, or CMake cache values from
# introducing unsupported paths into the built profile.
git init "$metis_build_root/source"
git -C "$metis_build_root/source" fetch --depth=1 https://github.com/ggml-org/llama.cpp.git "$metis_source_pin"
git -C "$metis_build_root/source" checkout --detach "$metis_source_pin"
test "$(git -C "$metis_build_root/source" rev-parse HEAD)" = "$metis_source_pin"
git -C "$metis_build_root/source" apply --check --unidiff-zero --whitespace=error "$metis_applied_patch"
git -C "$metis_build_root/source" apply --unidiff-zero --whitespace=error "$metis_applied_patch"

cmake -S "$metis_build_root/source" -B "$metis_build_root/build" \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    -DGGML_BACKEND_DL=OFF -DGGML_METAL=OFF -DGGML_BLAS=OFF \
    -DGGML_OPENMP=OFF -DGGML_NATIVE=OFF \
    -DLLAMA_BUILD_APP=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF \
    -DLLAMA_SUBPROCESS=OFF -DLLAMA_OPENSSL=OFF
cmake --build "$metis_build_root/build" --target llama-server --parallel "${METIS_LLAMA_BUILD_JOBS:-4}"
python3 -I "$metis_repo_root/src/metis/evaluation/native_build_identity.py" \
    "$metis_build_root/build" "$metis_source_pin" "$metis_applied_patch" "$metis_build_root/native-build.json"
printf '%s\n' "$metis_build_root/build/bin/llama-server"
