This fork follows upstream [Syncthing](https://github.com/syncthing/syncthing) and applies patches below in order. `automation` owns patches and workflows; generated `main` contains upstream source plus these patches. Nightly builds follow upstream default branch; stable builds follow upstream releases.

# Patched Syncthing

Applied patches, oldest first:

1. [Synchronize root-level `.stignore` files](https://github.com/felixfoertsch/syncthing/blob/automation/patches/sync-stignore.patch)
2. [Identify patched builds in the web UI](https://github.com/felixfoertsch/syncthing/blob/automation/patches/webui-build-marker.patch)

See [fork maintenance](https://github.com/felixfoertsch/syncthing/blob/automation/patches/README.md).

---

