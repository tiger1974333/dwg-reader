# DWG reader setup and recovery

Prefer GNU LibreDWG `dwgread`. Its official CLI supports `-O JSON` and `-o output.json`: [GNU program manual](https://www.gnu.org/software/libredwg/manual/html_node/Programs.html). Invoke with an argument list so spaces and Chinese paths remain intact.

## Find and reuse

The extraction script checks `--dwgread`, `DWGREAD_BIN`, PATH, then `$CODEX_HOME/tools/libredwg/*/bin/dwgread` (or `~/.codex/tools/...`). Check a trusted binary's `--version` and `--help`; flags may change.

## Build only when needed

Release sources are on [the official GNU archive](https://ftp.gnu.org/gnu/libredwg/) and [GNU mirrors](https://www.gnu.org/prep/ftp.html). Version 0.14 was used for the originating workflow; it is an example, not a claim to be the latest release.

Use a writable task directory or persistent user tool cache. Release tarballs include `configure`. Dependencies include a C compiler, make, and real pkg-config/pkgconf. Obtain missing dependencies through an authorized package manager or build them in the same user cache. Do not silently install system-wide.

After extracting a verified release:

```bash
./configure --disable-bindings --disable-shared --disable-docs --prefix=/writable/cache/libredwg/0.14
make -j4
make install
/writable/cache/libredwg/0.14/bin/dwgread --version
```

Do not use `--disable-json` or `--disable-dxf`, which removes the needed output path. Consult [official build instructions](https://github.com/LibreDWG/libredwg) and the release's `configure --help` if options fail. Save configure/build logs. Supply real pkg-config when absent; do not replace dependency checks with a command that always reports success. Preserve a working reader in a persistent cache instead of a temporary directory.

## Recovery

- Check DWG signature, permissions, output space, reader version, and stderr log.
- Raw JSON may expand a modest drawing to hundreds of megabytes. Stream it and avoid printing the whole file. `minJSON` reduces whitespace but does not fix unsupported objects.
- Unknown/proxy/custom objects can stay unreadable after conversion succeeds. Inventory retains counts/type IDs. Standard text and geometry do not prove full coverage of Tianzheng or other custom classes.
- Nonzero exits and truncated JSON require investigation. Use explicit partial mode only for valid remaining JSON and state limits. Do not repeat the same failing conversion indefinitely.
- `ezdxf` reads DXF, not binary DWG; use it after actual conversion.
