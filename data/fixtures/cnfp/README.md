# Public-forest register fixtures (CNFP)

Cut from three real editions of the Forest Service's Cadastro Nacional de
Florestas Públicas, clipped to boxes of about 6.5 km around every polling
place of the two fixture towns (TSE 05533 / IBGE 1507706, 2024; TSE 04367 /
IBGE 1507979, 2008), simplified to 0.002 degrees. GeoJSON; tests write each to
a zipped shapefile with pyshp, like the real download.

| File | Edition | Fields kept | Features |
| --- | --- | --- | --- |
| `cnfp_2008_sample.geojson` | 2008 (old schema) | `nome`, `tipo_flor`, `categoria`, `data_cria` | 9: 7 GLEBA (TIPO B), 1 FLONA, 1 RESEX |
| `cnfp_2024_sample.geojson` | 2024 retificado | `nome`, `tipo`, `categoria`, `anocriacao` | 81, including PA, PAE, PAE / APA and 3 GLEBA ARRECADADA |
| `cnfp_2025_sample.geojson` | 2025 | `nome`, `tipo`, `categoria`, `anocriacao` | 55, including PA, PAE and 2 GLEBA ARRECADADA |

The real schemas differ by edition: 2008 uses `tipo_flor` and long category
names (`Terra Indígena`, `GLEBA`, with `;` between categories); 2012 onward use
`tipo` and abbreviations (`TI`, `PA`, `PAE`, `GLEBA ARRECADADA`, with ` / `
between categories). `anocriacao` is a date written `dd/mm/yyyy` (or empty);
2012 has `ano` instead.

None of these fixtures contains an indigenous land: none lies near the two
towns. Tests add one polygon of their own for that layer.

With the rules of task 14, the 2024 fixture's 18 polling places are 5 inside
a settlement and 15 within 2 km (15 within 5 km), and none within 5 km of
undesignated land; the 2008 stations of town 04367 (14) are 0 inside a
settlement, 3 within 2 km and 12 within 5 km, and 2 inside undesignated land,
12 within 2 km and 14 within 5 km.
