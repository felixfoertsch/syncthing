This fork follows upstream [Syncthing](https://github.com/syncthing/syncthing) and applies [0001](https://github.com/felixfoertsch/syncthing/blob/patch-queue/patches/0001-sync-stignore.patch), [0002](https://github.com/felixfoertsch/syncthing/blob/patch-queue/patches/0002-webui-build-marker.patch) in order. `patch-queue` owns patches and workflows; generated `main` contains upstream source plus these patches. Nightly builds follow upstream default branch; stable builds follow upstream releases.

# Patched Syncthing

Applied patches, oldest first:

1. [Synchronize root-level `.stignore` files](https://github.com/felixfoertsch/syncthing/blob/patch-queue/patches/0001-sync-stignore.patch)
2. [Identify patched builds in the web UI](https://github.com/felixfoertsch/syncthing/blob/patch-queue/patches/0002-webui-build-marker.patch)

See [fork maintenance](https://github.com/felixfoertsch/syncthing/blob/patch-queue/patches/README.md).

---

[![Syncthing][14]][15]

---

[![MPLv2 License](https://img.shields.io/badge/license-MPLv2-blue.svg?style=flat-square)](https://www.mozilla.org/MPL/2.0/)
[![CII Best Practices](https://bestpractices.coreinfrastructure.org/projects/88/badge)](https://bestpractices.coreinfrastructure.org/projects/88)
[![Go Report Card](https://goreportcard.com/badge/github.com/syncthing/syncthing)](https://goreportcard.com/report/github.com/syncthing/syncthing)

## Goals

Syncthing is a **continuous file synchronization program**. It synchronizes
files between two or more computers. We strive to fulfill the goals below.
The goals are listed in order of importance, the most important ones first.
This is the summary version of the goal list - for more
commentary, see the full [Goals document][13].

Syncthing should be:

1. **Safe From Data Loss**

   Protecting the user's data is paramount. We take every reasonable
   precaution to avoid corrupting the user's files.

2. **Secure Against Attackers**

   Again, protecting the user's data is paramount. Regardless of our other
   goals, we must never allow the user's data to be susceptible to
   eavesdropping or modification by unauthorized parties.

3. **Easy to Use**

   Syncthing should be approachable, understandable, and inclusive.

4. **Automatic**

   User interaction should be required only when absolutely necessary.

5. **Universally Available**

   Syncthing should run on every common computer. We are mindful that the
   latest technology is not always available to every individual.

6. **For Individuals**

   Syncthing is primarily about empowering the individual user with safe,
   secure, and easy to use file synchronization.

7. **Everything Else**

   There are many things we care about that don't make it on to the list. It
   is fine to optimize for these values, as long as they are not in conflict
   with the stated goals above.

## Getting Started

Take a look at the [getting started guide][2].

There are a few examples for keeping Syncthing running in the background
on your system in [the etc directory][3]. There are also several [GUI
implementations][11] for Windows, Mac, and Linux.

## Docker

To run Syncthing in Docker, see [the Docker README][16].

## Getting in Touch

The first and best point of contact is the [Forum][8].
If you've found something that is clearly a
bug, feel free to report it in the [GitHub issue tracker][10].

If you believe that you’ve found a Syncthing-related security vulnerability,
please report it by emailing security@syncthing.net. Do not report it in the
Forum or issue tracker.

## Building

Building Syncthing from source is easy. After extracting the source bundle from
a release or checking out git, you just need to run `go run build.go` and the
binaries are created in `./bin`. There's [a guide][5] with more details on the
build process.

## Signed Releases

Release binaries are GPG signed with the key available from
https://syncthing.net/security/. There is also a built-in automatic
upgrade mechanism (disabled in some distribution channels) which uses a
compiled in ECDSA signature. macOS and Windows binaries are also
code-signed.

## Documentation

Please see the Syncthing [documentation site][6] [[source]][17].

All code is licensed under the [MPLv2 License][7].

[1]: https://docs.syncthing.net/specs/bep-v1.html
[2]: https://docs.syncthing.net/intro/getting-started.html
[3]: https://github.com/syncthing/syncthing/blob/main/etc
[5]: https://docs.syncthing.net/dev/building.html
[6]: https://docs.syncthing.net/
[7]: https://github.com/syncthing/syncthing/blob/main/LICENSE
[8]: https://forum.syncthing.net/
[10]: https://github.com/syncthing/syncthing/issues
[11]: https://docs.syncthing.net/users/contrib.html#gui-wrappers
[13]: https://github.com/syncthing/syncthing/blob/main/GOALS.md
[14]: assets/logo-text-128.png
[15]: https://syncthing.net/
[16]: https://github.com/syncthing/syncthing/blob/main/README-Docker.md
[17]: https://github.com/syncthing/docs


---

<a id="docker-container-for-syncthing"></a>

# Docker Container for Syncthing

Use the Dockerfile in this repo, or pull the `syncthing/syncthing` image
from Docker Hub.

Use the `/var/syncthing` volume to have the synchronized files available on the
host. You can add more folders and map them as you prefer.

Note that Syncthing runs as UID 1000 and GID 1000 by default. These may be
altered with the `PUID` and `PGID` environment variables. In addition
the name of the Syncthing instance can be optionally defined by using
`--hostname=syncthing` parameter.

To grant Syncthing additional capabilities without running as root, use the
`PCAP` environment variable with the same syntax as that for `setcap(8)`.
For example, `PCAP=cap_chown,cap_fowner+ep`.

To set a different umask value, use the `UMASK` environment variable. For
example `UMASK=002`.

## Example Usage

**Docker cli**
```
$ docker pull syncthing/syncthing
$ docker run --network=host  -e STGUIADDRESS= \
    -v /wherever/st-sync:/var/syncthing \
    syncthing/syncthing:latest
```

**Docker compose**
```yml
---
version: "3"
services:
  syncthing:
    image: syncthing/syncthing
    container_name: syncthing
    hostname: my-syncthing
    environment:
      - PUID=1000
      - PGID=1000
      - STGUIADDRESS=
    volumes:
      - /wherever/st-sync:/var/syncthing
    network_mode: host
    restart: unless-stopped
    healthcheck:
      test: curl -fkLsS -m 2 127.0.0.1:8384/rest/noauth/health | grep -o --color=never OK || exit 1
      interval: 1m
      timeout: 10s
      retries: 3
```

## Discovery

Please note that Docker's default network mode prevents local IP addresses
from being discovered, as Syncthing can only see the internal IP address of
the container on the `172.17.0.0/16` subnet. This would likely break the ability
for nodes to establish LAN connections properly, resulting in poor transfer
rates unless local device addresses are configured manually.

It is therefore strongly recommended to stick to the [host network mode](https://docs.docker.com/network/host/),
as shown above.

Be aware that syncthing alone is now in control of what interfaces and ports it
listens on. You can edit the syncthing configuration to change the defaults if
there are conflicts.

## GUI Security

By default Syncthing inside the Docker image listens on `0.0.0.0:8384`. This
allows GUI connections when running without host network mode. The example
above unsets the `STGUIADDRESS` environment variable to have Syncthing fall
back to listening on what has been configured in the configuration file or the
GUI settings dialog. By default this is the localhost IP address `127.0.0.1`.
If you configure your GUI to be externally reachable, make sure you set up
authentication and enable TLS.
