# Third-party notices

PyYAML ships with the app. The Windows runtime builder unpacks CPython and the four wheels listed below. Paths are relative to `nbapp/`.

| Component | Licence | Distributed licence text |
|---|---|---|
| PyYAML 6.0.3 | MIT | `vendor/yaml/LICENSE` |
| CPython 3.14.10 embeddable distribution | Python Software Foundation License Version 2 and incorporated notices | `runtime/LICENSE.txt` |
| NumPy 2.5.4 | BSD-3-Clause | `runtime/Lib/site-packages/numpy-2.5.4.dist-info/licenses/LICENSE.txt` and component notices in that licence directory |
| RDKit 2026.9.1 | BSD-3-Clause | Licence files in `runtime/Lib/site-packages/rdkit-2026.9.1.dist-info/` from the RDKit wheel |
| Pillow 12.3.0 | MIT-CMU | Licence files in `runtime/Lib/site-packages/pillow-12.3.0.dist-info/` from the Pillow wheel |
| openclatura 0.4.4 | MIT | `runtime/Lib/site-packages/openclatura-0.4.4.dist-info/licenses/LICENSE` from the openclatura wheel |
| Ketcher standalone 3.18.0 and embedded EPAM Indigo | Apache-2.0 | `sketcher/LICENSE-ketcher.txt`, `sketcher/NOTICE-ketcher.txt` |
| React, React DOM, scheduler, Lodash/Underscore, object-assign, buffer, regenerator-runtime, url-search-params-polyfill and Three.js | MIT | `sketcher/ketcher/static/js/*.LICENSE.txt`, including the notice beside the 127 viewer chunk |
| SheetJS crc32.js and EPAM Miew 0.11.1 | Copyright notices in the release | `sketcher/ketcher/static/js/main.e47c48ad.js.LICENSE.txt` and `127.aa15387f.chunk.js.LICENSE.txt` in the same directory |
| Additional Ketcher dependencies | FreeBSD Documentation, MIT, X11, AFL-3.0, Apache 1.0 and 2.0, BSD 2- and 3-clause, ISC, LGPL-2.1, MPL-1.0, public domain and Unlicense | `sketcher/NOTICE-ketcher.txt` lists these collectively without a component-by-component mapping. |

Redistribute the complete runtime directory to retain the wheel metadata, licences and accompanying component notices.
