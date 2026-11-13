# rast-package-template

A forkable starter for publishing a **third-party package** that the
[RAST](https://github.com/Enricko/rast) Package Center installs with
**Install from GitHub**. It ships a working example — **Lua 5.4**, built as
static binaries from the lua.org source release for `linux-x86_64` and
`linux-aarch64` — plus the manifest schema and a release workflow. Validation,
smoke tests and release checks are performed by the Rust `rast package`
commands from the [RAST](https://github.com/Enricko/rast) release, so the
template cannot drift from what the Package Center accepts; no Python is
needed.

| Repository | Responsibility |
|---|---|
| [Enricko/rast](https://github.com/Enricko/rast) | Package Center, installer, validation, authorization, jobs |
| [Enricko/rast-packages](https://github.com/Enricko/rast-packages) | Official signed catalog (Python, PHP CLI, Go, Node.js) |
| **Enricko/rast-package-template** (this) | Starter for packages published from your own GitHub repository |

## How a release becomes installable

1. You push a tag `v<version>-<revision>` (for example `v5.4.9-1`).
2. [`release.yml`](.github/workflows/release.yml) builds on native x86_64 and
   aarch64 runners, runs the same version checks RAST runs, attests build
   provenance, writes `rast-package.json` and publishes a GitHub release with:
   * `lua-5.4.9-linux-x86_64.tar.gz`, `lua-5.4.9-linux-aarch64.tar.gz`
   * `rast-package.json` — the manifest, pinning each archive by URL, size and SHA-256
3. The workflow then runs `rast package check-release`, the same cross-check
   RAST performs before it shows a preview.

In RAST: **Package Center → Install from GitHub**, paste the repository or
release link, review the preview (publisher, repository, release, version,
targets, verification checks), approve the source, and install. RAST:

* resolves the link to **one release** (a repository link means its latest
  release) and reads `rast-package.json` from it;
* refuses artifacts that are not assets of that same release, whose size or
  SHA-256 differs from what GitHub reports for the asset, or that are hosted
  anywhere else (downloads may only redirect within GitHub's release hosts);
* pins the install to the inspected release and digests (the preview expires
  after 30 minutes);
* binds the repository to the publisher id on first approval — a later release
  that declares another publisher is refused;
* never lets a third-party package take an id from the official catalog.

The package is validated by exactly the same rules as official packages, then
downloaded, verified, extracted (no absolute paths, `..`, devices or links
leaving the package), checked, and installed side by side under
`/var/lib/rast/packages/runtimes/<id>/<version>/`.

## Fork and publish your own package

1. **Fork** this repository (or use it as a template).
2. Edit [`package.json`](package.json):
   * `manifest.id` — your package id (lowercase, digits, dashes; not one of the
     official ids `python`, `php`, `go`, `nodejs`).
   * `manifest.publisher` — **your** id, name and URL. RAST binds your
     repository to this id the first time an administrator approves it.
   * `manifest.runtime.executables` and `checks` — relative paths inside the
     archive and commands whose output must contain `expect` (`{version}` is
     replaced with the version).
   * `source` — the upstream source URL and its SHA-256.
3. Adapt [`scripts/build.sh`](scripts/build.sh) to build your software into
   `<id>-<version>/bin/...` and write `dist/<id>-<version>-<target>.tar.gz`.
   Prefer static binaries; otherwise declare `requires.glibc` and host notes.
4. Check locally (download the Rust tool once from the
   [RAST release](https://github.com/Enricko/rast/releases); replace `v0.11.6`
   with the release named in the workflow):
   ```sh
   mkdir -p bin
   curl -fsSL -o bin/rast https://github.com/Enricko/rast/releases/download/v0.11.6/rast-linux-x86_64
   chmod +x bin/rast
   bash scripts/build.sh linux-x86_64 dist
   ./bin/rast package smoke dist/<id>-<version>-linux-x86_64.tar.gz --package package.json
   ./bin/rast package manifest --tag v<version>-1 --repo <owner>/<repo> --dist dist --allow-missing --out dist/rast-package.json
   ./bin/rast package validate dist/rast-package.json --dist dist
   ```
5. Publish: `git tag v<version>-1 && git push origin v<version>-1`.
6. Import it in RAST with the release link.

To ship a rebuilt archive of the same upstream version, bump the revision
(`v5.4.9-2`). RAST offers a newer revision as a reinstall.

## Manifest

The format is documented by [`schema/rast-package.schema.json`](schema/rast-package.schema.json)
(JSON Schema 2020-12) and enforced by `rast package validate`, which uses
RAST's own manifest validator. Key fields:

| Field | Meaning |
|---|---|
| `schemaVersion`, `kind` | `1`, `"rast-package"` |
| `id`, `type` | package id; `runtime` (types `app` and `service` are reserved for later schema versions) |
| `publisher` | `{id, name, url}` — who publishes; bound to the repository |
| `version`, `revision` | upstream version (also the install directory) and package revision |
| `channel` | optional update stream (default `major.minor`) |
| `minRastVersion` | oldest RAST that can install it |
| `runtime.executables` | relative paths of the commands, shown with their installed paths |
| `runtime.checks` | commands run without a shell after extraction and again from the final location |
| `artifacts[]` | per host target: `url`, `sha256`, `size`, `format: tar.gz`, `stripComponents`, `requires`, `provenance` |

## The example

Lua is built with `make posix MYLDFLAGS=-static` (no `dlopen`, no readline), so
the binaries need no host libraries. The source tarball is refused unless its
SHA-256 matches the value in `package.json`, taken from the
[lua.org download page](https://www.lua.org/ftp/).

## License

MIT (template). Lua is MIT licensed; its license is included in each archive.
