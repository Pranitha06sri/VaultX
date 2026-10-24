# Third-party notices

The application is distributed under AGPL-3.0-only because its required PyMuPDF/MuPDF integration uses the AGPL licensing option. Dependency licenses and notices remain applicable. Dependencies are obtained through package managers; this repository does not bundle model weights.

| Component | License / reference |
| --- | --- |
| PyMuPDF / MuPDF | GNU Affero GPL 3.0 or Artifex commercial terms; this MVP uses the AGPL option. [Official licensing](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright). |
| React / React DOM | MIT. |
| Vite / Vitest | MIT. |
| TypeScript | Apache-2.0. |
| Tailwind CSS | MIT. |
| Lucide | ISC for library code; icon assets include ISC and MIT notices. See the installed `lucide-react/LICENSE`. |
| FastAPI / Pydantic | MIT. |
| Starlette | BSD-3-Clause. |
| SQLAlchemy | MIT. |
| Uvicorn / HTTPX | BSD-3-Clause. |
| Pillow | MIT-CMU (historical PIL license); bundled image libraries have additional notices. |
| python-multipart / python-dotenv | Apache-2.0 / BSD-3-Clause. |
| pytest | MIT. |
| Gemma 4 (optional external weights) | Apache-2.0; [official model card](https://ai.google.dev/gemma/docs/core/model_card_4). |
| PaddleOCR (optional external install) | Apache-2.0; [official license](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE). PaddlePaddle, OCR model assets, and transitive dependencies have their own terms. |

For authoritative copies of all transitive license texts, consult each installed Python distribution's `*.dist-info` metadata/licenses and npm package's `LICENSE`/`NOTICE` files. Installing a hosted inference client or configuring a hosted endpoint does not make that provider's service open source. Commercial PyMuPDF licensing, model-hosting terms, and any separately installed dependencies must be evaluated independently before redistribution or deployment.
