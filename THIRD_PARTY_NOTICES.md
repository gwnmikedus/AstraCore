# Third party notices

The root [LICENSE](LICENSE) covers AstraCore's original software code and project documentation. The materials below retain their respective owners and terms. Dependency installation does not relicense those dependencies under AstraCore's license.

## EVE Online materials

Bundled EVE commodity, planet and structure icons, ship renders, corporation and alliance logos, EVE SSO button graphics, and game data come from EVE's services. They are excluded from the PolyForm license. Access, use and distribution are subject to the [EVE Developer License Agreement](https://developers.eveonline.com/license-agreement) and applicable service terms. A fork or separate deployment must satisfy those terms and register its own EVE application where required; AstraCore cannot grant rights belonging to EVE's owner.

The bundled image inventory and original sources are recorded in [the image manifest](src/astracore/static/img/eve/manifest.json). The application includes its EVE copyright and trademark notice on its Credits page. The applicable notice is also reproduced here:

EVE Online material is used under the EVE Developer License: © 2014 CCP hf. All rights reserved. "EVE", "EVE Online", "CCP", and all related logos and images are trademarks or registered trademarks of CCP hf.

AstraCore is an independent fan project and is not endorsed or supported by EVE's owner. No EVE trademark rights are granted by AstraCore's license.

## Bundled fonts

| Material | Publisher | Terms shipped with the fonts |
|---|---|---|
| Barlow and Barlow Condensed | [The Barlow Project](https://github.com/jpt/barlow) | [Complete upstream SIL Open Font License 1.1](src/astracore/static/fonts/Barlow-OFL.txt) |
| IBM Plex Mono | [IBM Plex](https://github.com/IBM/plex) | [Complete upstream SIL Open Font License 1.1 and Reserved Font Name notice](src/astracore/static/fonts/IBM-Plex-OFL.txt) |

These are self-hosted Latin WOFF2 subsets originally supplied by Google Fonts. Font licensing remains separate from the application license. Preserve the complete copyright and license notices when redistributing fonts.

## Bundled icons

[Lucide](https://github.com/lucide-icons/lucide) SVG icons are covered by the [ISC license bundled in this repository](src/astracore/static/icons/LICENSE), including the upstream Feather attribution. Their ISC permission and notice remain in force independently of PolyForm.

## Downloaded templates and static data

[DalShooth's PI templates](https://github.com/DalShooth/EVE_PI_Templates) and [Fuzzwork's static data exports](https://www.fuzzwork.co.uk/dump/) are downloaded at runtime into the ignored data directory. They are not AstraCore-authored files and are not covered by the root license. Preserve their source attribution and check the publisher's applicable permissions before repackaging or redistributing them. Where no explicit redistribution license is supplied, a public download alone is not treated as a grant from AstraCore.

[VOC Hauling](https://vochauling.com/) supplies courier tariffs; its names and published service information remain its own. A quote shown by AstraCore is not a booking or a guarantee of service availability.

## Installed dependencies

FastAPI, Starlette, Uvicorn, Jinja, HTTPX, PuLP/CBC, cryptography, PyJWT and other installed dependencies retain their own licenses. Their notices are distributed with those packages. Release builders must preserve the notices required by the actual dependency versions they include, especially when packaging dependencies into a standalone distribution.

## License sources

The PolyForm text in `LICENSE` was downloaded unchanged from [the publisher's plain text](https://polyformproject.org/licenses/noncommercial/1.0.0.txt). Complete font notices were downloaded from [Barlow's OFL file](https://github.com/jpt/barlow/blob/main/OFL.txt) and [IBM Plex's license file](https://github.com/IBM/plex/blob/master/LICENSE.txt). These records identify the source of the notices; they do not replace their terms.
