# Research and development backlog — Solara

Based on the specifications in `docs/product`, reviewed on 2026-10-05.

The destination repository and application are named **Solara**. The local directory is `/Users/fox/estudos/TERRA-Open-Energy`; this path is neither the repository name nor the application name. This repository (`lucertae-research`) produces research, evaluations and data contracts; Solara receives the calculations and features. The cross-reference below is based on inspection of application code at commit `8579c87` on 2026-10-05. “Existing” means an implementation was identified, not that the interface or external sources were fully validated.

## Scope and sources

- **SP**: [solara-platform.tex](docs/product/solara-platform.tex), version 0.2: primary source for requirements, products, architecture, caveats and evolution.
- **ML**: [machine_learning_energy_sector.tex](docs/product/machine_learning_energy_sector.tex): foundations and evaluation criteria; does not imply automatic inclusion of every application in Solara.
- **DT**: [data_taks.tex](docs/product/data_taks.tex): task families and national sources for research and validation.

Proposed priorities: **P0** corrects interpretation or establishes a dependency; **P1** improves an existing product; **P2** extends its capabilities after validation. These are not delivery estimates. `Sxx` identifies task dependencies. The acceptance criteria below are engineering proposals derived from the documentation.

## Shared foundation

### S01 — Verify feature status in the code · P0

**Solara cross-reference:** Partially addressed by this inspection; runtime validation remains.

**Integration points** (relative to the Solara repository root): `README.md`; `sidecar/terra_energy_engine/registry.py`; `frontend/src/lib/project.ts`.

**Scope adjustment:** Complete the matrix by running all six products and recording discrepancies; do not repeat the structural inventory below.

**Goal:** Turn the status declared in the Evolution section into a verifiable inventory.

**Deliverable:** Matrix of the six products, inputs, calculations, screens, exports, limitations and implementation locations; classify each item as existing, partial or absent.

**Acceptance:** Every classification has code evidence and, where executable, a demonstration; differences from the specification are recorded; completed tasks are closed and partial tasks have their scope adjusted.

**Source:** SP, Evolution and Products. **Dependencies:** None.

### S02 — Unify inputs and execution preconditions · P0

**Solara cross-reference:** Existing foundation: capabilities, operators with poll, runner and shared graph.

**Integration points** (relative to the Solara repository root): `frontend/src/lib/capabilities.ts`; `frontend/src/lib/operators.ts`; `frontend/src/lib/runGraph.ts`; `frontend/src/lib/analysis.ts`; `internal/sidecar/runner.go`.

**Scope adjustment:** Audit consistency across entry points and extend diagnostics per input; preserve existing infrastructure.

**Goal:** Ensure the card, empty reading and operators run the same product with the same parameters.

**Deliverable:** Single contract for inputs, defaults and states; availability diagnostics by place, map extent and store contents.

**Acceptance:** Inputs use the states not set, pending, reading, read and error; a missing source or store blocks execution with a visible reason; global products work without a store; equivalent runs through different entry points produce the same parameters; cancellation terminates the sidecar and permits another run.

**Source:** SP, R3, R4, R8, R10, Sequence of a run and Architecture. **Dependencies:** S01.

### S03 — Preserve context and invalidate results after changes · P0

**Solara cross-reference:** Place/parameter snapshots, stale detection and undo exist; versioned provenance needs auditing and extension.

**Integration points** (relative to the Solara repository root): `frontend/src/lib/project.ts`; `frontend/src/lib/analysis.ts`; `frontend/src/lib/projectFile.ts`; `frontend/src/lib/export.ts`; `app_project.go`.

**Scope adjustment:** Add source and calculation identity/versioning; check invalidation when the store or source changes, as well as place and parameters.

**Goal:** Prevent an old result from being presented as a calculation for the current place or parameters.

**Deliverable:** Snapshot of place, source, effective parameters, calculation version and execution time; stale-result detection.

**Acceptance:** Changing a place or parameter marks the result stale without changing its original identity; saving and reopening preserves context and rasters; undo restores the corresponding state; CSV uses local time with an offset and JSON uses full UTC; failure or cancellation does not publish a partial result as complete.

**Source:** SP, R5, R10, Layout of a reading and Architecture. **Dependencies:** S01, S02.

### S04 — Standardize qualifications and result comparison · P0

**Solara cross-reference:** Readings and exports exist; complete standardization remains to be checked.

**Integration points** (relative to the Solara repository root): `frontend/src/components/energy/`; `frontend/src/lib/table.ts`; `frontend/src/lib/export.ts`.

**Scope adjustment:** Extend existing components and schema, preserving qualifications in tables and exports.

**Goal:** Keep units, coverage, data type and caveats beside the numbers they qualify.

**Deliverable:** Shared components for provenance, modeled/observed, raw/not validated, at least, injected/not generated and not confirmed; comparison table with context.

**Acceptance:** Readings, summaries and exports preserve units and qualifications; comparison identifies place, period, source and parameters; unknown data do not appear as zero; grid proximity and curtailment remain separate; no aggregate indicator hides quantities of different kinds.

**Source:** SP, R6, R7, Layout of a reading and Standing caveats. **Dependencies:** S03.

## Usable ground

Declared existing capabilities: slope, HAND and permanent-water removal.

### S05 — Handle missing coverage in the water mask · P0

**Solara cross-reference:** Confirmed gap: water.mask returns water and covered, but missing classification produces a non-water mask.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/terrain/water.py`; `sidecar/terra_energy_engine/terrain/usable.py`; `sidecar/terra_energy_engine/terrain/actions.py`.

**Scope adjustment:** Propagate covered through classification, denominators, readings and GeoTIFF; do not create another water reader.

**Goal:** Correct the interpretation that can currently count sea without data as land.

**Deliverable:** Mask distinguishing land, water and unknown coverage; coverage diagnostics.

**Acceptance:** Missing data are not silently classified as land; coastal reference areas do not count identified sea as usable ground; complete source absence blocks calculation; legend and reading indicate unknown area and fraction denominators.

**Source:** SP, Conditions of each product and Standing caveats. **Dependencies:** S01, S04.

### S06 — Include land cover, mangroves and wetlands · P1

**Solara cross-reference:** WorldCover mask exists; general land-use classification was not identified in the product.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/terrain/water.py`; `sidecar/terra_energy_engine/stac.py`; `sidecar/terra_energy_engine/terrain/usable.py`.

**Scope adjustment:** Reuse STAC access and the grid; add rules and coverage provenance.

**Deliverable:** Land-cover source reader and configurable exclusion rules, with version and year recorded. Evaluate MapBiomas as a candidate without assuming its classes are equivalent to WorldCover classes.

**Acceptance:** Selected classes change the map and usable area; water, slope, HAND and land cover have individual and overlapping counts without double counting the total; mangroves and wetlands are identified where the source distinguishes them; nodata remains explicit.

**Source:** SP, Evolution; DT, Siting and land use and MapBiomas sources. **Dependencies:** S05.

### S07 — Add protected-area restrictions · P1

**Solara cross-reference:** Protected-area integration was not identified in the current calculation.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/terrain/usable.py`; `frontend/src/components/energy/GroundDocument.tsx`.

**Scope adjustment:** Add a source, rasterization/overlay and rule to the existing product.

**Deliverable:** Assessment of public sources, overlay layer and explicit exclusion or flagging rule by category.

**Acceptance:** Source, date and category accompany each restriction; users can inspect why a parcel was excluded; overlaps do not duplicate area; the product presents screening restrictions without issuing a permitting conclusion.

**Source:** SP, Evolution. **Dependencies:** S06; source selection and validation.

### S08 — Measure the largest contiguous usable block · P1

**Solara cross-reference:** Classification and summary exist; the largest contiguous component was not identified.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/terrain/usable.py`; `internal/energy/types_ground.go`; `frontend/src/components/energy/GroundDocument.tsx`.

**Scope adjustment:** Calculate components of the final mask and extend the contract/summary without creating a separate product.

**Deliverable:** Connected components of the final mask, largest block in hectares and inspection layer.

**Acceptance:** Connectivity rule is declared; separate islands are not summed as one block; results respect the resolution and projection used for area calculation; the reading shows total usable area and largest block separately; exports preserve block identity.

**Source:** SP, Evolution. **Dependencies:** S06; incorporate S07 when available.

### S09 — Evaluate HAND sensitivity to the calculation margin · P1

**Solara cross-reference:** HAND is implemented and tested.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/terrain/hand.py`; `sidecar/tests/test_hand.py`.

**Scope adjustment:** Run the sensitivity study in research and transfer only demonstrated changes.

**Deliverable:** Experiment with margins and reference areas, measuring excluded-area differences, cost and effects of external drainage.

**Acceptance:** Results quantify sensitivity; memory/time limits and effective margin are recorded; the “at least” qualification remains until the upstream basin is adequately represented; any rule change is compared with the previous version.

**Source:** SP, Standing caveats. **Dependencies:** S01, S05.

## Solar resource and photovoltaic generation

Declared existing capabilities: point reanalysis, 1 kWp reference array and losses represented by a single ratio.

### S10 — Compare a satellite solar source with reanalysis · P1

**Solara cross-reference:** NASA POWER solar source and PV chain exist.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/sun/nasa_power.py`; `sidecar/terra_energy_engine/sun/record.py`; `sidecar/terra_energy_engine/energy/pv.py`.

**Scope adjustment:** Compare candidates in research and integrate a source adapter after validation.

**Deliverable:** Assessment of candidate source, coverage, access, temporal resolution and license; comparison with available measurements before offering source selection.

**Acceptance:** Compare the same quantities and periods; distinguish GHI from POA and observed from modeled values; report bias, error and coverage by site/station; retain sources and limitations in the result; a new source does not replace the current one solely because it has higher resolution.

**Source:** SP, Evolution; DT, Resource assessment; ML, Solar generation forecasting and Evaluation. **Dependencies:** S01, S04.

### S11 — Offer published solar-resource maps · P2

**Solara cross-reference:** Layer infrastructure exists; a catalog of ready-made solar maps was not identified.

**Integration points** (relative to the Solara repository root): `frontend/src/lib/mapEngine.ts`; `frontend/src/lib/mapState.ts`; `sidecar/terra_energy_engine/energy/overlays.py`.

**Scope adjustment:** Integrate published layers with metadata; do not duplicate Solar terrain.

**Deliverable:** Catalog of ready-made maps, area clipping, legend and value queries with period and resolution.

**Acceptance:** Published maps remain distinguishable from Solar terrain calculations; monthly and annual values have unambiguous units; coverage and nodata are shown; source/edition and usage permissions are recorded; exports preserve georeferencing.

**Source:** SP, Evolution. **Dependencies:** S10; source selection.

### S12 — Add a module and inverter catalog · P1

**Solara cross-reference:** The PV model uses reference-array constants.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/energy/pv.py`; `internal/energy/types.go`; `frontend/src/lib/params.ts`.

**Scope adjustment:** Introduce equipment/configuration into requests, calculations, bindings and persistence.

**Deliverable:** Equipment selection and array configuration, retaining the 1 kWp reference option.

**Acceptance:** Effective parameters and catalog version are persisted; invalid combinations have diagnostics; DC capacity, AC capacity and DC/AC ratio are explicit; different equipment changes the simulation traceably; the current reference remains comparable.

**Source:** SP, Evolution, Photovoltaic generation. **Dependencies:** S02, S03.

### S13 — Break down photovoltaic losses · P1

**Solara cross-reference:** The physical chain already includes transposition, IAM, temperature, DC and inverter calculations; omitted losses are compensated through a reference PR.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/energy/pv.py`; `sidecar/tests/test_pv.py`.

**Scope adjustment:** Break down additional losses and review PR application; do not reimplement existing physical mechanisms.

**Deliverable:** Losses by mechanism, separating modeled from assumed losses, with an energy balance.

**Acceptance:** Configurable losses and defaults appear in the reading and snapshot; losses are not applied twice; inverter clipping is distinguished from other losses; the sum/balance reconciles energy before and after losses; evaluation compares with the previous single ratio.

**Source:** SP, Evolution; ML, Solar generation forecasting. **Dependencies:** S12.

### S14 — Incorporate the horizon into point solar calculations · P1

**Solara cross-reference:** Solar terrain already calculates horizon effects; point resource uses its own chain.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/energy/terrain_irradiance.py`; `sidecar/terra_energy_engine/energy/pv.py`.

**Scope adjustment:** Evaluate horizon reuse and transfer it to the point calculation while preserving the distinction between terrain plane and array plane.

**Deliverable:** DEM-derived horizon profile, shading effect and comparison with the scenario without a horizon.

**Acceptance:** Profile by azimuth, resolution and queried extent are inspectable; energy with/without shading is reported; DEM failures are shown; distinguish terrain shading from local obstacles not represented; reuse of Solar terrain code depends on verified equivalence.

**Source:** SP, Evolution and Solar terrain. **Dependencies:** S03, S13.

## Wind resource and generation — Wind screening

Declared existing capabilities: reanalysis at 10/50 m, shear extrapolation and a fixed turbine; gross, unvalidated results.

### S15 — Evaluate a wind source at hub height · P1

**Solara cross-reference:** MERRA-2 10/50 m, shear and diagnostics are implemented.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/energy/wind.py`; `sidecar/tests/test_wind.py`.

**Scope adjustment:** Compare source/height and transfer improvements into the existing assess function.

**Deliverable:** Comparison of the current source with candidates at the relevant height, including coverage, density and temporal treatment.

**Acceptance:** Comparison uses compatible heights and periods; shows the effects of shear and source on speed and energy; does not convert mean wind speed into energy as if it were an hourly series; the unvalidated label changes only with documented evidence.

**Source:** SP, Evolution and Standing caveats; ML, Wind generation forecasting. **Dependencies:** S01, S04.

### S16 — Represent terrain and roughness in wind screening · P2

**Solara cross-reference:** Shear and diagnostic equivalent roughness exist; spatial roughness/terrain modeling was not identified.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/energy/wind.py`; `sidecar/terra_energy_engine/terrain/dem.py`.

**Scope adjustment:** Add spatial characterization without confusing the current diagnostic with a validated correction.

**Deliverable:** Characterization of surrounding terrain and roughness, accompanied by an assessment of the method for applying these data to wind.

**Acceptance:** Resolution, classes and assumptions are explicit; correction is compared with current extrapolation; DEM resolution is not presented as effective wind resolution; unvalidated sites remain identified.

**Source:** SP, Evolution, Wind resource. **Dependencies:** S15; land-cover source validated in S06 where applicable.

### S17 — Import mast measurements and validate wind · P2

**Solara cross-reference:** A mast importer was not identified in the product.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/energy/wind.py`; `frontend/src/components/energy/WindDocument.tsx`.

**Scope adjustment:** Define local import and its contract before implementation; retain the scope decision.

**Deliverable:** Local import of series with height, unit and time zone; quality control and comparison with the modeled source.

**Acceptance:** Detect duplicate timestamps, gaps and invalid values; preserve originals and filters; align heights/periods; report error and coverage; no private series is sent to external services. Because this involves user data, the task requires an explicit review of the scope statement “no product depends on customer data”.

**Source:** SP, Evolution and Scope; ML, Wind generation forecasting. **Dependencies:** S15; product decision on local import.

### S18 — Replace the fixed turbine with a turbine catalog · P1

**Solara cross-reference:** IEA-3.4-130 reference turbine and density normalization exist.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/energy/wind.py`; `internal/energy/types.go`.

**Scope adjustment:** Replace fixed selection with a catalog while preserving the original curve and assumptions.

**Deliverable:** Power curves, characteristics and turbine selection with provenance.

**Acceptance:** Hub height, rated power, reference density and curve limits are persisted; no silent curve extrapolation; results show density and loss assumptions; the original turbine remains available for comparison; evaluation distinguishes gross from net energy.

**Source:** SP, Evolution, Wind generation. **Dependencies:** S03, S15.

### S19 — Simulate turbine layout and wake effects · P2

**Solara cross-reference:** Layout or wake calculations were not identified.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/energy/wind.py`; `frontend/src/lib/project.ts`.

**Scope adjustment:** Develop after the catalog, with a new layout object and result contract.

**Deliverable:** Editable layout and declared wake model, with scenarios with/without interaction.

**Acceptance:** Positions and parameters are saved; geometric constraints have diagnostics; wind direction enters the calculation; wake losses do not duplicate generic losses; farm total and per-turbine results can be checked. Define how layouts relate to catalog areas before implementation.

**Source:** SP, Evolution. **Dependencies:** S18, S16; decision on layout representation.

### S20 — Evaluate long-term wind correction · P2

**Solara cross-reference:** Long-term correction using local measurements was not identified.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/energy/wind.py`.

**Scope adjustment:** Validate in research first; integrate after the importer and scope decision.

**Deliverable:** Method relating local measurements to a reference series, with validation in a separate period.

**Acceptance:** State the overlap and reference periods; compare corrected results with the original source; evaluate outside the fitting period; report uncertainty and limitations; do not use future data in validation.

**Source:** SP, Evolution; ML, Evaluation. **Dependencies:** S17.

## Grid connection

Declared existing capabilities: lines, substations, connection bus, headroom and curtailment in Brazil.

### S21 — Verify bus linkage, geometry and headroom interpretation · P0

**Solara cross-reference:** Point/voltage linkage, headroom and separation of curtailment are already implemented.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/grid/congestion.py`; `sidecar/terra_energy_engine/grid/curtailment.py`; `frontend/src/components/energy/ConnectionDocument.tsx`.

**Scope adjustment:** Treat as a linkage/coverage audit and regression task; do not rebuild bus selection.

**Deliverable:** Review of plant–bus linkage and presentation of voltage, unknown capacity, geometry and curtailment.

**Acceptance:** Buses at the same coordinate are not selected solely by distance; voltage and published linkage can be checked; distance to a straight segment appears as a lower bound; missing capacity remains null; headroom explains its formula and scope without suggesting authorized capacity; curtailment has its own period and coverage.

**Source:** SP, Conditions of each product, Grid store, R7 and Standing caveats. **Dependencies:** S01, S04.

### S22 — Incorporate the connection queue when a verifiable source exists · P2

**Solara cross-reference:** A connection-queue source or integration was not identified.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/grid/congestion.py`; `sidecar/terra_energy_engine/grid/actions.py`.

**Scope adjustment:** Research the source and establish verifiable linkage before changing headroom.

**Deliverable:** Study of access, identifiers, coverage and updates; link requests to buses where possible.

**Acceptance:** Requests are not treated as operational projects; status and date accompany records; ambiguous links are flagged; absence of information does not mean an empty queue; impact on headroom is calculated only with a documented rule and sufficient data.

**Source:** SP, Evolution. **Dependencies:** S21; source validation.

### S23 — Validate and improve international grids through the existing contract · P1

**Solara cross-reference:** International support is already implemented: contract v1, loader, readers and catalog.

**Integration points** (relative to the Solara repository root): `contract/v1.sql`; `contract/load.py`; `sidecar/terra_energy_engine/grid/contract.py`; `sidecar/tests/test_contract.py`; `frontend/src/lib/places.ts`.

**Scope adjustment:** Treat as end-to-end validation with an international dataset and diagnostic improvements; do not build a new contract.

**Deliverable:** Validation of the `solara` v1 contract and adaptation of menus/layers to available data.

**Acceptance:** Verify EPSG:4326 and MW/kV/MVA; countries without the `br` schema offer only what the contract supports; do not offer curtailment or consumption absent from the contract; preserve unknown values; run with a non-Brazilian reference database.

**Source:** SP, Grid store and Evolution. **Dependencies:** S02, S21.

### S24 — Evaluate power-flow feasibility · P2, study

**Solara cross-reference:** The current product calculates context/proximity; an electrical power-flow solver was not identified.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/grid/congestion.py`; `sidecar/terra_energy_engine/grid/contract.py`.

**Scope adjustment:** Keep as a study; the current geometric contract is insufficient for power flow.

**Deliverable:** List of required electrical data, store gaps and an offline proof of concept with a reference network.

**Acceptance:** Topology, impedances, loads, generation and operating conditions have defined sources; balance and convergence are checked against a reference solution; results are not calculated solely from current geometries; the recommendation states maintenance cost and screening limitations.

**Source:** SP, Evolution; ML, Formulation: AC power flow. **Dependencies:** S21; electrical contract to be defined. Product implementation depends on the study outcome.

## Area consumption

Declared existing capabilities: monthly area consumption from the BDGD of one distribution utility per run.

### S25 — Validate coverage and time reference already offered before execution · P0

**Solara cross-reference:** Coverage before and after execution is already implemented through demand_reach, reach and coverage.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/grid/demand.py`; `sidecar/terra_energy_engine/grid/actions.py`; `frontend/src/components/editors/RunInputs.tsx`; `frontend/src/components/energy/DemandDocument.tsx`.

**Scope adjustment:** Validate utility/year selection, partial coverage and persistence; improve only discrepancies.

**Deliverable:** Utility/year selection and calculation of the intersection between the catalog area and the footprint of the sets.

**Acceptance:** The card reports the covered fraction before execution; partial readings are marked; footprint is not called a concession area; the map does not position consumers as if their coordinates were individual addresses; results with different years or coverage make those differences explicit.

**Source:** SP, R3, R9, Area by catalog and Standing caveats. **Dependencies:** S02, S04.

### S26 — Replace opaque capacity normalization with an auditable rule · P0

**Solara cross-reference:** Unit heuristic confirmed in NORMALISED_KWP, with POWER_SPLIT_KW=75.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/grid/demand.py`; `sidecar/tests/test_demand.py`.

**Scope adjustment:** Investigate ambiguous cases and extend traceability without renaming injection as generation.

**Deliverable:** Diagnosis of mixed units and a normalization procedure with evidence per source/record; identification of ambiguous cases.

**Acceptance:** Original values and transformations remain traceable; identify cases not resolved by the “above 75” heuristic; show impact on totals; do not turn ambiguity into certainty; MMGD injection remains separate from generation and self-consumption.

**Source:** SP, Standing caveats. **Dependencies:** S25.

### S27 — Define and document BDGD schema preparation · P1

**Solara cross-reference:** The reader requires bdgd.unidade_ponto and mentions bdgd_para_postgis.py; a BDGD loader was not identified in this repository.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/grid/demand.py`; `README.md`.

**Scope adjustment:** Locate the external loader and document preparation; contract/load.py loads the generic contract and does not replace the BDGD loader.

**Deliverable:** Identify the loading program, minimum contract, reproducible procedure and integrity checks.

**Acceptance:** A machine prepared from the documentation runs Area consumption; the schema records utility, year and sources; validations reconcile totals and keys; Solara retains read-only store access; do not embed writes in the product to address the missing loader.

**Source:** SP, R8 and Open questions, BDGD loader. **Dependencies:** S25, S26.

### S28 — Define expansion to hourly load curves and tariffs · P2, decision and study

**Solara cross-reference:** Current consumption is monthly; a customer curve or tariff engine was not identified.

**Integration points** (relative to the Solara repository root): `sidecar/terra_energy_engine/grid/demand.py`; `frontend/src/components/energy/DemandDocument.tsx`.

**Scope adjustment:** Retain the scope decision/study before implementation.

**Deliverable:** Proposal for local curves and tariff sources, with units, validity dates and comparison with monthly consumption.

**Acceptance:** Observed curves and estimated profiles are distinguished; tariffs include category and validity dates; consumption and cost remain separate; no monthly curve is presented as an hourly measurement; importing customer data and using tariff regulations require scope definition and source verification before implementation.

**Source:** SP, Evolution, Consumption, Scope and Open questions. **Dependencies:** S25; product decision.

## Suggested sequence

1. **Verify and stabilize:** S01–S04, S05, S21, S25 and S26.
2. **Improve existing products:** S06–S10, S12–S15, S18, S23 and S27, respecting dependencies.
3. **Expand with evidence:** S11, S16–S17, S19–S20, S22, S24 and S28.

Solar terrain has no specific gap in the Evolution list. Apply shared tasks and check the four-million-cell limit, horizon shading, legend and float32 GeoTIFF export during S01; open specific tasks only from observed discrepancies or needs.

## Outside this cycle

Finance, storage/hybrids, market/revenue, wind environmental impact, land tenure/permitting and system planning appear as new workstreams. They are not improvements to existing features. They depend on data, chaining between results or product decisions.

Forecasting models from the experiments are not included automatically either: the current specification does not calculate its own forecasts. Incorporation requires defining the product, scale, input availability and evidence against the adversary; an isolated research gain is insufficient.

## Transferring research features into the application

Inference using `lucertae` models was not identified in the current action registry. The GFS wind field is a third-party forecast, not an integration of those models. The following tasks establish the research → sidecar → shell → interface path.

### S29 — Define the contract for a research feature · P0

**Deliverable:** Versioned input/output schema, unit, target, horizon, geographic scale, issue time, sources, availability and qualifications; experiment → candidate product matrix.

**Acceptance:** Each candidate has an adversary, evaluation outside training and limitations; state whether the calculation is descriptive, historical or predictive; do not present SIN-aggregated curtailment as a municipal forecast; do not present price/emissions results as point attributes without justification; models with insufficient evidence remain experimental.

**Integration:** Research in `src/lucertae/evaluation.py` and `src/lucertae/registry.py`; application in `sidecar/terra_energy_engine/registry.py`, `protocol.py` and `internal/energy/` or `internal/grid/`. **Dependencies:** S01, S04; explicit product decision on internally generated forecasts.

### S30 — Produce a reproducible calculation or model package · P1

**Deliverable:** Artifact containing version, features and their order, preprocessing, unit, training/evaluation window, dependencies, configuration and reference predictions. Deterministic calculations use a method version instead of a model artifact.

**Acceptance:** Inference works outside ignored folders on the research machine; the reference set reproduces values within a defined tolerance; missing data have an explicit rule; no training routine starts when querying a place; the artifact does not depend on the researcher's absolute paths.

**Integration:** Producer in `experiments/`; consumer in `sidecar/terra_energy_engine/`. **Dependencies:** S29; available experiment producer and controls that effectively block execution.

### S31 — Integrate a pilot feature into the protocol and application · P1

**Deliverable:** Select a candidate after S29; add a Python action, Go request/result, Wails binding, parameters, reading and export.

**Acceptance:** Values match the S30 reference; preconditions, progress and cancellation use existing infrastructure; results record method/model and sources; old projects still open; experimental features are identified; no server or store writes are required.

**Integration:** `sidecar/terra_energy_engine/registry.py`, `app_energy.go`/`app_grid.go`, `internal/energy/`/`internal/grid/`, `frontend/src/lib/analysis.ts`, `project.ts`, `operators.ts`, `runGraph.ts`, `table.ts` and reading components. **Dependencies:** S29, S30, S03.

### S32 — Enforce temporal source availability during inference · P0 for forecasting

**Deliverable:** Input policy by issue time, coverage validation and delayed-source diagnostics; store issue time and valid time separately from execution time.

**Acceptance:** Removing a source or delaying publication prevents improper use; observations after issue time do not enter as features; `mtime` alone is not proof of historical publication; fallback to the adversary occurs only when defined in the contract and is shown in the reading; without valid inputs, do not publish a number as a completed forecast.

**Integration:** Research in `src/lucertae/gate.py`; application in the source adapter and pilot feature action. **Dependencies:** S29; required before releasing forecasts in S31.

### S33 — Validate the transferred feature with regression checks and independent evaluation · P1

**Deliverable:** Inference references and missing/delayed-input scenarios, version comparison and pilot acceptance report.

**Acceptance:** Separate implementation parity from predictive quality; run temporal evaluation with an adversary and appropriate intervals; negative results are not hidden; verify readings/exports/versioning; define criteria to promote, retain as experimental or remove the model. Comparison does not require continuous monitoring or a remote service.

**Integration:** `sidecar/tests/`, existing Go tests, interface type checking and evaluation in `lucertae-research`. **Dependencies:** S31, S32 where applicable.

## Cross-reference findings and revised order

- **Implemented foundation to audit/extend:** S02–S04, S21, S23 and S25. S01 has advanced through this inspection and should focus on runtime validation.
- **Directly evidenced gaps:** Unknown water coverage handling (S05), heuristic BDGD capacity units (S26), reference PV model without a catalog/full loss breakdown (S12–S13), fixed turbine and lack of external wind validation (S15/S18).
- **Extensions not identified in the inspected code:** General land cover, protected areas, contiguous blocks, equipment catalog, mast measurements, wakes, connection queue and electrical solver. Absence is a finding of targeted inspection, not evidence that every execution path was exercised.
- **Research transfer:** Start with S29 and S30; S32 blocks internally generated forecasts; then S31 and S33. Select the pilot by scale, available data and evidence, without automatically promoting the experiment with the highest skill.

Practical order: complete S01 at runtime → fix S05/S26 and extend provenance in S03 → develop P1 improvements → transfer the pilot through S29–S33 → assess P2 expansions.

The inspection did not modify Solara application files. No remote-source queries or visual desktop validation were performed.

**Verification performed:** Selected tests from `test_usable.py`, `test_contract.py`, `test_demand.py` and `test_energy_actions.py`: 63 tests passed before a pending psycopg query was interrupted. The selection did not finish, so this is not full suite approval or complete database validation. Rasterio deprecation warnings were emitted. The backlog was structurally checked: 33 unique IDs and 28 application cross-reference entries.
