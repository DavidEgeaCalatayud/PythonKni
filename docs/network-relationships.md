# Network Relationship Evidence

PythonKni separates **asset discovery** from **relationship evidence**. The Network Topology view never treats a line on the graph as proof of a physical cable, switch port or Wi-Fi association unless a future evidence source can justify that claim.

## Confidence levels

- `CONFIRMED`: a logical relationship is supported by direct local evidence. Current examples are the operating-system default route matching an online inventory asset, or an online in-scope asset with a valid local neighbor MAC observation.
- `INFERRED`: the relationship is plausible from the current snapshot but lacks one of the stronger evidence signals. An online in-scope host without a valid neighbor MAC is the current example.
- `UNKNOWN`: the asset is historical/offline or the local system cannot map the default gateway to a current asset.

These levels describe confidence in the **logical relationship being displayed**. They do not currently prove a physical attachment point.

## Current passive evidence sources

The relationship layer reads only information already available locally:

1. persistent Network Intelligence assets;
2. IP scope membership;
3. MAC/neighbor information collected by the existing local discovery flow;
4. the operating-system IPv4 default route (`route print` on Windows).

No credentials, authentication attempts, packet injection, internet-wide discovery or additional port scans are introduced by this layer.

## Persistence

Relationship snapshots are stored in the same Network Intelligence SQLite database, in the independent `network_relationships` table. Each row preserves:

- scope;
- source and target identifiers;
- relationship kind;
- confidence;
- evidence strings;
- observation timestamp.

A completed scan replaces the relationship snapshot for that scope. A cancelled/incomplete scan does **not** replace it, so partial discovery cannot create false topology state.

## Topology rendering

The topology uses line style to communicate confidence:

- solid: `CONFIRMED`;
- dashed: `INFERRED`;
- dotted: `UNKNOWN`.

The line tooltip exposes the relationship kind and the exact evidence used.

## Future physical-topology evidence

The data model is designed so future sources can add stronger relationship kinds without replacing Asset Inventory. Candidates include LLDP observations, managed-switch bridge/MAC tables and explicitly configured SNMP reads on infrastructure the operator is authorized to administer.

Until such evidence exists, PythonKni intentionally avoids claiming switch, access-point or cabling paths.
