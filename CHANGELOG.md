# Changelog

## [1.1.1](https://github.com/Manteplante/local-branch-overview-norway/compare/v1.1.0...v1.1.1) (2026-11-24)


### Documentation

* uploaded presentation in norwegian ([d511042](https://github.com/Manteplante/local-branch-overview-norway/commit/d511042b2dfef36aef65c2fe4fc96b82bb5b5192))

## [1.1.0](https://github.com/Manteplante/local-branch-overview-norway/compare/v1.0.0...v1.1.0) (2026-11-22)


### Features

* easier-to-hit map markers and an activity panel on hover/click ([cfe0fd9](https://github.com/Manteplante/local-branch-overview-norway/commit/cfe0fd91de25c7a692b4a349b59d7bbff4fd88e0))
* follow linked activities pages and add make scrape-empty ([4a219a1](https://github.com/Manteplante/local-branch-overview-norway/commit/4a219a1de874401bfc2fed7c685a70b05e7e7aaa))
* geocode branches by their street address first ([e3f3279](https://github.com/Manteplante/local-branch-overview-norway/commit/e3f32797ad1d7e7f0fc9c3d98629882102e96b97))
* geocode more branches: cross-county districts, former municipalities, name parts ([e3deb7f](https://github.com/Manteplante/local-branch-overview-norway/commit/e3deb7f879c049e64459351a49e449c580cd955c))
* hand-entered branch locations via data/overrides.csv ([5a9b0f4](https://github.com/Manteplante/local-branch-overview-norway/commit/5a9b0f40775f8defd1c044b2c9613162433c7feb))
* ran make transform to register new data ([8377ec7](https://github.com/Manteplante/local-branch-overview-norway/commit/8377ec7917878e396b386f8f7129ed6cba699fa9))
* redesigned home and map pages with data-quality notes, credits and a specific-activity filter ([3f932bb](https://github.com/Manteplante/local-branch-overview-norway/commit/3f932bbaaafcaeb16b52cfbc341798ba24bf2cb4))


### Bug Fixes

* format run.py to satisfy ruff format check ([24273e2](https://github.com/Manteplante/local-branch-overview-norway/commit/24273e238bc91390d85a2b1ab0c0a4b3ab8f6e5e))
* ignore placeholder site coordinates and prefer namesake municipalities over hamlets ([af2475c](https://github.com/Manteplante/local-branch-overview-norway/commit/af2475cf3a3f388cce09e56a1f18caf36a589e51))
* preserve rows on incomplete linked scrapes ([1966eb9](https://github.com/Manteplante/local-branch-overview-norway/commit/1966eb939ca65bccdffc6a47ab84e655002e0c58))


### Documentation

* README with quick start, stack and sources; simpler data-quality doc and cheat sheet ([943e342](https://github.com/Manteplante/local-branch-overview-norway/commit/943e342b31298a6d2bc7a98657dbfa02c4535ae9))

## [1.0.0](https://github.com/Manteplante/local-branch-overview/compare/v0.4.0...v1.0.0) (2026-11-20)


### ⚠ BREAKING CHANGES

* geocode with Kartverket place names instead of Google

### Features

* add sample scrape target, Oslo support and progress output ([ff0bad6](https://github.com/Manteplante/local-branch-overview/commit/ff0bad624bdd3d67e3060562bf96e5798f7bb7ca))
* geocode branches without coordinates via Google ([bd606a9](https://github.com/Manteplante/local-branch-overview/commit/bd606a9ed605b1b79ab0497d5947baf17ba0509a))
* geocode with Kartverket place names instead of Google ([a09243c](https://github.com/Manteplante/local-branch-overview/commit/a09243c61826d09a97d484111c029eee5abd186b))


### Documentation

* plan for missing branch addresses and coordinates ([bd5990b](https://github.com/Manteplante/local-branch-overview/commit/bd5990ba84950c28b4163deea0ff1a934119f306))

## [0.4.0](https://github.com/Manteplante/local-branch-overview/compare/v0.3.0...v0.4.0) (2026-11-10)


### Features

* add Streamlit dashboard with map of local branches ([293b5c8](https://github.com/Manteplante/local-branch-overview/commit/293b5c85a8736a3f33d61625d5e47851e062bc3d))

## [0.3.0](https://github.com/Manteplante/local-branch-overview/compare/v0.2.0...v0.3.0) (2026-11-10)


### Features

* add polite scraper for local branches ([1df636e](https://github.com/Manteplante/local-branch-overview/commit/1df636ef074b66c504a25fc1fd3c292fb9cf0cd8))
* uv set up and basic structure ([0d08659](https://github.com/Manteplante/local-branch-overview/commit/0d0865907d60e850b67be2e40fd0217a173aae8a))


### Bug Fixes

* parse all district layouts and split Trøndelag into Nord and Sør ([74246e3](https://github.com/Manteplante/local-branch-overview/commit/74246e3f681c6ff49e76e2ee7bb2b62a8bde81e6))
* restore package module and add selenium ([9fd2ceb](https://github.com/Manteplante/local-branch-overview/commit/9fd2ceb60a7a4f5bb4ba3488d7ff8149b08cce91))

## [0.2.0](https://github.com/Manteplante/local-branch-overview/compare/v0.1.0...v0.2.0) (2026-11-06)


### Features

* uv set up and basic structure ([0d08659](https://github.com/Manteplante/local-branch-overview/commit/0d0865907d60e850b67be2e40fd0217a173aae8a))
