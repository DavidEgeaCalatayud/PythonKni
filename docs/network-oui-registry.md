# Network Intelligence OUI registry

PythonKni identifies the manufacturer of globally administered unicast MAC addresses from a registry that is bundled with the application. Vendor lookup is deliberately **offline at runtime**: Network Intelligence does not contact IEEE or any other third party when scanning or viewing devices.

## Source and scope

The checked-in registry is generated from the public **IEEE Registration Authority MA-L CSV**:

- source: `https://standards-oui.ieee.org/oui/oui.csv`
- registry type: MA-L / 24-bit OUI
- generated asset: `assets/network_oui_prefixes.csv`
- provenance sidecar: `assets/network_oui_prefixes.meta.json`

MA-M and MA-S are intentionally outside this updater. They use 28-bit and 36-bit assignments respectively and require a different longest-prefix matching contract. Adding them must be treated as a separate runtime feature rather than silently truncating them to 24 bits.

## Deterministic normalization

`scripts/update_oui_registry.py` treats the downloaded IEEE file as untrusted maintenance input and applies a strict, reproducible transformation:

1. the source must be UTF-8 CSV and contain `Registry`, `Assignment` and `Organization Name`;
2. every accepted row must be `MA-L`;
3. assignments must normalize to exactly six hexadecimal digits and are rendered as `AA-BB-CC`;
4. vendor names are Unicode NFC-normalized, Unicode format controls such as zero-width spaces are removed, and whitespace is collapsed;
5. empty vendor names, invalid prefixes, malformed CSV and unexpected registry types fail the update;
6. output entries are sorted lexicographically by OUI and written with canonical CSV headers/newlines;
7. the generated registry must contain at least 20,000 unique assignments, preventing a truncated upstream response from replacing the bundled dataset.

Given identical source bytes, the generated registry bytes are identical.

## Duplicate IEEE assignments

The IEEE public MA-L data contains a small number of historical duplicate OUI assignments. PythonKni never resolves these by arbitrary row order.

When the same OUI has multiple distinct organization names, the updater:

- detects the conflict;
- sorts the organization names deterministically;
- stores one unique OUI row whose vendor value preserves every conflicting organization separated by ` / `;
- records the conflict in `network_oui_prefixes.meta.json` under `duplicate_assignments`.

Exact duplicate rows for the same normalized OUI/vendor collapse to one entry. The bundled CSV therefore always has unique prefixes while retaining upstream ambiguity instead of silently overwriting it.

## Provenance metadata

The metadata sidecar records:

- schema version and generator;
- IEEE source name and URL;
- UTC retrieval timestamp;
- source `ETag` and `Last-Modified` when supplied;
- SHA-256 of the raw IEEE source;
- SHA-256 of the normalized bundled registry;
- unique assignment count;
- duplicate-assignment count and the conflicting organizations.

CI and release validation recompute the registry SHA-256 and validate these invariants without network access.

## Updating the registry

Manual maintenance refresh:

```powershell
python scripts/update_oui_registry.py update
```

Offline integrity validation:

```powershell
python scripts/update_oui_registry.py validate
```

For deterministic tests or incident analysis, `update` also accepts a local `--source-file` and does not require network access in that mode.

## Scheduled maintenance

`.github/workflows/oui-registry-maintenance.yml` runs monthly and can also be started manually. It downloads the IEEE MA-L CSV only in this maintenance workflow.

If the normalized registry or its source provenance changed, the workflow:

1. validates the generated registry locally;
2. creates a dedicated `automation/oui-registry-*` branch;
3. commits only the registry and metadata files using the repository owner's configured Git identity;
4. opens a pull request against `main`;
5. dispatches the normal Windows CI workflow for that branch.

No automatic maintenance update writes directly to `main`.

## Runtime behavior

`pythonkni/network_intelligence/oui.py` continues to load only the bundled CSV. It contains no updater or HTTP path. If the registry cannot be read, vendor enrichment degrades to no vendor result rather than attempting an external lookup.

`PythonKni.spec` bundles the complete `assets/` directory, so both the registry and its provenance metadata are included in the packaged Windows application.
