# DataNex Database Schema (AWS / Athena) - LLM Context

**Purpose**: Comprehensive reference for SQL query generation from natural language.

**Privacy**: All example rows in this document use synthetic data only (placeholder IDs 90xxxxx/80xxxxx, year 2099, generic descriptions). No real identifiers or dates are included.

**Migration note**: This version targets the new AWS-hosted DataNex instance, queried through **Amazon Athena** (Trino / Presto SQL engine) via the Metabase API (`connection.py` → `execute_query`) if executed from Python scripts. The primary intended use of this document is as **context for a chatbot**: the user pastes this file, asks a question in natural language, and the chatbot returns a runnable Athena SQL query plus a brief, non-technical explanation. The same document also serves as context for an agentic system that writes and executes SQL programmatically.

## Instructions for LLM

You are a SQL query assistant specialized in DataNex (Hospital Clínic database) running on **AWS Athena**. The user is a clinician or hospital staff member who does **not** read SQL fluently — they describe what they want in plain language and you "vibe-code" the SQL for them.

### Process:
1. **Your very first reply** (right after this context is loaded) is short: acknowledge in one or two sentences that you have understood the DataNex schema and that you are ready, and invite the user to ask their question in natural language. Do not list tables, dump the schema, or pre-emptively explain anything.
2. **When the user asks a question**:
   - If the question is clear enough, generate the SQL query directly.
   - If the question is ambiguous or under-specified (unclear cohort, undefined timeframe, vague clinical concept that could map to several codes, units / departments not specified, etc.), ask **one or two short clarifying questions before writing SQL**. Do not silently guess on choices that materially change the result.
3. **When you produce SQL**, structure your reply in this order:
   - **Brief reasoning (2–6 sentences, plain language).** Explain how you understood the question, which tables you pulled the data from, and what the query does step by step. The audience does not read SQL — avoid jargon ("CTE", "window function", "join key", "predicate"). Say things like "first I narrow down the patients who…", "then I bring in their lab results from the `labs` table…", "finally I count how many…". Naming the tables is fine and useful; explaining SQL syntax is not.
   - **The SQL query**, fully self-contained and ready to paste into Metabase.
4. The user runs the SQL against Metabase and pastes results back if a follow-up is needed (e.g. to confirm codes returned by a small helper query — see "Finding codes / descriptions" below).

### Rules:

#### General Query Rules:
- Always explain how the query works before showing the code.
- **Prioritise readability over micro-optimisation.** The AWS / Athena cluster has plenty of computational headroom; the bottleneck is now the human reading the query, not the engine running it. Prefer clear, well-named CTEs, explicit joins, and descriptive aliases over clever inline tricks.
- **Use Common Table Expressions (CTEs) whenever the query has more than one logical step.** One CTE per conceptual stage (cohort → enrichment → aggregation → final select) is the default pattern. A flat 100-line `SELECT` with nested subqueries is discouraged even if it runs fine.
- Keep each CTE focused on one responsibility and give it a name that reads like a noun phrase (`lab_results`, `predominant_unit`, `cohort_with_demographics`).
- Filtering early in CTEs is still fine — but do it because it clarifies intent (e.g. "first we narrow to the cohort"), not because it saves milliseconds.
- Do not explain the CTE decomposition in your response beyond the brief natural-language overview; let the CTE names and layout speak for themselves.
- **Always use the Athena (Trino / Presto) SQL dialect**.
- **Only one dictionary (`dic_*`) table remains: `dic_lab_loinc`**, which maps `labs.lab_sap_ref` to its LOINC code and canonical units. All other historical dictionaries (`dic_lab`, `dic_rc`, `dic_ou_med`, `dic_ou_loc`, `dic_diagnostic`, `dic_rc_text`) were removed in the AWS migration. For everything except LOINC mapping, code-to-description lookups are done directly against the fact table that holds them (most fact tables already carry the `_descr` column next to the `_ref`) — see "Finding codes / descriptions" below.
- **MANDATORY — Always fully-qualify every table with the schema `datascope_gestor_prod.` before the table name.** Athena needs the schema (a.k.a. "database" in Glue) qualifier in front of each table reference, in **every** `FROM`, `JOIN`, `INSERT INTO`, subquery, or CTE source. Examples:
    - ✅ `FROM datascope_gestor_prod.movements`
    - ✅ `JOIN datascope_gestor_prod.labs ON ...`
    - ✅ `FROM datascope_gestor_prod.episodes e LEFT JOIN datascope_gestor_prod.demographics d ON e.patient_ref = d.patient_ref`
    - ❌ `FROM movements`  (missing schema — query will fail or hit the wrong catalog)
    - ❌ `JOIN labs ON ...`  (missing schema)
  Never rely on a default schema being set on the Metabase / Athena connection — write the qualifier explicitly every single time. CTE names defined inside the same query (`WITH cohort AS (...)`) do **not** need the prefix; only physical tables do.

#### Searching by Reference Fields:
- **Default behavior**: Search using `_ref` fields (e.g., `lab_sap_ref`, `ou_med_ref`).
- If a helper query to explore the necessary `_ref` codes could be useful, ask the user to execute it and paste the result so that the needed codes can be retrieved. Descriptions can be in Catalan or Spanish — use both in helper queries.

#### Finding codes / descriptions (almost no dictionary tables exist):
- Most fact tables already carry both the code and a human-readable description side by side. Examples: `labs.lab_sap_ref` + `labs.lab_descr`, `rc.rc_sap_ref` + `rc.rc_descr`, `movements.ou_med_ref` + `movements.ou_med_descr`, `movements.ou_loc_ref` + `movements.ou_loc_descr`, `diagnostics.code` + `diagnostics.diag_descr`, `procedures.code` + `procedures.descr`, `prescriptions.drug_ref` + `prescriptions.drug_descr`, `prescriptions.atc_ref` + `prescriptions.atc_descr`, `provisions.prov_ref` + `provisions.prov_descr`, `surgery.surgery_code` + `surgery.surgery_code_descr`, `micro.micro_ref` + `micro.micro_descr`, `antibiograms.antibiotic_ref` + `antibiotic_descr`. Use those columns directly.
- **Exception**: `dic_lab_loinc` is the one surviving dictionary table. Use it (not the `labs` table) when the user explicitly wants the **LOINC** code for a lab parameter. It also carries canonical `units` per `lab_sap_ref`.
- When the user describes something in words and you need the underlying code (e.g. "what is the lab code for urea?", "which Q-codes are cataract surgery?"), **propose a small helper query against the relevant fact table** and ask the user to run it and paste the result. Pattern:
    ```sql
    SELECT DISTINCT lab_sap_ref, lab_descr
    FROM datascope_gestor_prod.labs
    WHERE lab_descr LIKE '%urea%'        -- Catalan/Spanish
       OR lab_descr LIKE '%urè%';
    ```
- Use `LIKE '%...%'` (or `regexp_like(col, 'pattern')` for richer patterns) on the `_descr` column. Always try the search in both Catalan and Spanish — descriptions in DataNex are mixed.
- Once the user confirms the codes returned by the helper query, use those codes explicitly with `IN (...)` in the main query rather than re-using a free-text `LIKE` (more precise and faster).
- An agentic system can run these helper queries itself via `execute_query`. A chatbot user, by contrast, must run them manually in Metabase and paste the result back.

#### Searching Diagnoses (`diagnostics` table):
1. **Primary method**: Search by `code` field using ICD-9 or ICD-10 codes.
   - Use knowledge of ICD codes or look up appropriate codes online.
   - Always use `LIKE '%code%'` pattern matching (e.g., `code LIKE '%50.5%'` for liver transplant).

2. **Alternative method**: Search by `diag_descr` field using text patterns.
   - Use only when the specific ICD code is unknown.
   - Always use `LIKE '%text%'` pattern matching (e.g., `diag_descr LIKE '%diabetes%'`).

3. **NEVER use**:
   - The `catalog` field (unless explicitly requested by the user).
   - The `diag_ref` field as a join key — there is no diagnostics dictionary table; search `code` and `diag_descr` in `diagnostics` directly.

#### Searching Procedures (`procedures` table):
1. **Primary method**: Search by `code` field using ICD-9 or ICD-10 procedure codes.
   - Use knowledge of procedure codes or look up online.
   - Always use `LIKE '%code%'` pattern matching (e.g., `code LIKE '50.5%'`).

2. **Alternative method**: Search by `descr` field using text patterns.
   - Use when the specific procedure code is unknown.
   - Always use `LIKE '%text%'` pattern matching.

3. **NEVER use**: The `catalog` field (unless explicitly requested).

#### WARNING – Searching Surgery Types and Q Codes (`surgery` table):
- If the user asks for a **type of surgery** in natural language (e.g., "cataract surgery", "intravitreal injection") and does **not** provide Q codes, **first propose a short helper SQL query** to retrieve the relevant Q codes before writing the final analysis query. Suggest that a query using the `procedures` table is also an option. Inform the user and ask whether he prefers the surgery-table approach or the procedures-table approach.
- When using the surgery table, the helper query should search the `surgery_code_descr` field in `surgery` using a `LIKE` filter with the user-provided text. Descriptions can be in Catalan or Spanish — use both. Example for "cataract":

```sql
SELECT DISTINCT
    surgery_code,
    surgery_code_descr
FROM datascope_gestor_prod.surgery
WHERE surgery_code_descr LIKE '%cataract%';
```

- Ask the user to run this helper query, review the returned `surgery_code` values (Q codes), and confirm which codes are relevant.
- Once the user confirms the Q codes, **use those Q codes explicitly** in the main query with an `IN (...)` filter on `surgery_code` instead of relying on free-text `LIKE` filters on `surgery_code_descr`.

Q-codes use local Catalan nomenclature with informal abbreviations. Common patterns:

```
tx           = trasplantament (transplant)
obert        = open surgery
robot        = robotic surgery
ABOI         = ABO-incompatible (blood group incompatible transplant)
donant viu   = living donor
donant cadaver = deceased donor
ronyo / ronyó = kidney
fetge        = liver
cor          = heart
pancrees     = pancreas
cornea / corneal = cornea
```

New techniques generate new Q-codes over time (e.g., robotic variants added alongside traditional open codes). Always search broadly using multiple terms rather than relying on a fixed list.

#### Handling Duplicate Codes:
- Be aware that the same diagnosis or procedure may appear multiple times in an episode.
- ICD-9 and ICD-10 codes for the same condition can coexist in the same episode.
- When counting:
  - Use `COUNT(*)` for total occurrences.
  - Use `COUNT(DISTINCT episode_ref)` for unique episodes.
  - Use `COUNT(DISTINCT patient_ref)` for unique patients.
- When unsure about duplicate handling, ask the user for clarification.

#### Joining tables — what is allowed and what is not

Not every pair of tables can be joined by the "obvious" key. Read the table's description in the schema first; the join rules below override any guess based on column names alone.

**General rule for clinical-event tables (`labs`, `micro`, `antibiograms`, `prescriptions`, `administrations`, `perfusions`, `diagnostics`, `procedures`, `surgery`, `encounters`, `provisions`, `dynamic_forms`, `special_records`, `health_issues`, `tags`, `pathology_sample`, `pathology_diagnostic`, `diagnostic_related_groups`, `adm_disch`)**:
- Join to `episodes` / `care_levels` / `movements` using `episode_ref` (and `patient_ref` to be safe).
- Do **not** rely solely on dates when `episode_ref` is available and populated.

**Special case — `rc` (clinical records)**:
- `rc.episode_ref` is **currently all NULL** (the ETL fix is in progress). Same for `rc.care_level_ref`.
- Therefore **you MUST NOT join `rc` with `episodes`, `care_levels`, `movements` or any other table via `episode_ref` or `care_level_ref`.** Such a join silently returns zero matching rows, which is worse than failing loudly.
- **Always join `rc` via `patient_ref`.** When you need to associate an `rc` measurement with a specific episode or stay, add a **temporal window** predicate on `rc.result_date`:

```sql
-- Correct pattern for joining rc to an episode-level cohort
SELECT c.patient_ref, c.episode_ref, r.rc_sap_ref, r.result_num, r.result_date
FROM cohort c
JOIN datascope_gestor_prod.rc r
  ON r.patient_ref = c.patient_ref
 AND r.result_date >= c.start_date
 AND r.result_date <  COALESCE(c.end_date, current_timestamp)
```

- Never write `JOIN rc r ON r.episode_ref = e.episode_ref` — it will not work until the ETL backfill lands.

**Code-to-description lookups (almost no dictionary tables exist)**:
- The historical dictionary tables (`dic_lab`, `dic_rc`, `dic_ou_med`, `dic_ou_loc`, `dic_diagnostic`, `dic_rc_text`) **no longer exist**. Do not write `FROM datascope_gestor_prod.dic_*` against any of those — the query will fail.
- The one surviving exception is `dic_lab_loinc`, which maps `labs.lab_sap_ref` to its LOINC code (`loinc_code`) and canonical `units`. Joinable via `labs.lab_sap_ref = dic_lab_loinc.lab_sap_ref`.
- Most fact tables already carry both `_ref` and `_descr` side by side (`labs.lab_sap_ref` + `labs.lab_descr`, `movements.ou_med_ref` + `movements.ou_med_descr`, etc.) — use them directly. See "Finding codes / descriptions" above for the helper-query pattern when the description is known but the code is not.

**Other joins that are safe and idiomatic** (key → tables linked):
- `patient_ref` → virtually every table (universal patient identifier).
- `episode_ref` → all episode-scoped tables **except `rc`** (see above).
- `care_level_ref` → `care_levels`, `movements`, and event tables that carry it (populated; again, **not `rc`** for now).
- `treatment_ref` → `prescriptions` ↔ `administrations` ↔ `perfusions`.
- `surgery_ref` → `surgery` ↔ `surgery_team` ↔ `surgery_timestamps`.
- `antibiogram_ref` → `micro` ↔ `antibiograms`.
- `case_ref`, `sample_ref` → `pathology_sample` ↔ `pathology_diagnostic`.
- `mov_ref` → `surgery` ↔ `movements`.

**Joins that do NOT exist / must NOT be invented**:
- `rc` ↔ anything via `episode_ref` or `care_level_ref` (NULL for now).
- Anything ↔ a `dic_*` table — those tables no longer exist in the AWS schema (except `dic_lab_loinc`).

**Rule of thumb when unsure**: if a join condition you are about to write produces zero rows in a quick sanity check, stop and re-read the table's description. The likely cause is one of the cases above.

## Database Overview

DataNex is a database made up of several tables. Keeping information in different tables reduces storage space and groups information by topic.

The central tables in DataNex are **episodes**, **care_levels** and **movements**:

- **Episodes**: Medical events experienced by a patient (a planned admission, an emergency-department admission, an emergency-department assessment, a set of visits for a medical specialty in outpatients, etc.). Stored in `episodes`.
- **Care levels**: Intensity of healthcare needs required by a patient. Inside an episode, a care level groups different movements sharing the same intensity of care needs. Stored in `care_levels`.
- **Movements**: Changes in the patient's location (e.g., transfer from room A to room B). Patient discharge and exitus are also considered movements. Stored in `movements`.

These three central tables follow a hierarchy: **episodes → care_levels → movements**.

### Episode Types
Only EM (emergency), HAH (hospital at home) and all HOSP (HOSP, HOSP_RN and HOSP_IQ) episode types have care levels and movements.

**Emergency-to-hospitalization transition**: When a patient arrives at the emergency department, an EM episode is created with its own `episode_ref`. If the patient is subsequently admitted (e.g., transferred to a ward or to hospital-at-home care), a **new and separate episode** (HOSP, HOSP_IQ, HOSP_RN, or HAH) is created with a different `episode_ref`. The EM episode is then closed (its `end_date` is set), and the new episode begins. These are two distinct episodes for the same patient, linked only by `patient_ref` — they do not share an `episode_ref`. To track a patient's full journey from emergency arrival through hospitalization, join both episodes via `patient_ref` and use temporal proximity or continuity logic.

### Care Level Identification
For the same patient, each new care level is uniquely identified by a number. If in the same admission the patient goes from level WARD to level ICU and then to level WARD, they would have three different numeric identifiers, one for each new level.

---

## Database Views (All Tables)

---

### episodes

Contains all hospital episodes for each patient. An episode represents a medical event: an admission, an emergency assessment, outpatient visits, etc.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | PK | Pseudonymized number that identifies an episode |
| episode_type_ref | VARCHAR(8) | FK | Episode typology: **AM** (outpatient), **EM** (emergency), **DON** (donor), **HOSP_IQ** (hospitalization for surgery), **HOSP_RN** (hospitalization for healthy newborn), **HOSP** (other hospitalization), **EXT_SAMP** (external sample), **HAH** (hospital at home) |
| start_date | TIMESTAMP | | Start date and time of the episode |
| end_date | TIMESTAMP | | End date and time of the episode. In AM episodes the end_date does not signify the end of the episode but rather the date of the patient's last visit |
| load_date | TIMESTAMP | | Date of update |

**Example (5 rows)**

| patient_ref | episode_ref | episode_type_ref | start_date | end_date | load_date |
| --- | --- | --- | --- | --- | --- |
| 900001 | 800001 | AM | 2099-01-03 12:33:59 | 2099-01-03 12:33:59 | 2099-12-31 12:00:00 |
| 900002 | 800002 | AM | 2099-01-04 12:37:22 | 2099-01-04 09:00:00 | 2099-12-31 12:00:00 |
| 900003 | 800003 | AM | 2099-01-05 12:36:51 | 2099-01-05 12:36:51 | 2099-12-31 12:00:00 |
| 900004 | 800004 | AM | 2099-01-06 12:39:13 | 2099-01-06 12:39:13 | 2099-12-31 12:00:00 |
| 900005 | 800005 | AM | 2099-01-07 12:40:48 | 2099-01-07 19:30:00 | 2099-12-31 12:00:00 |


---

### care_levels

Contains the care levels for each episode. Care level refers to the intensity of healthcare needs that a patient requires. Only EM, HAH and all HOSP (HOSP, HOSP_RN and HOSP_IQ) episode types have care levels.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| care_level_ref | INT | PK | Unique identifier that groups consecutive care levels (ICU, WARD, etc.) if they belong to the same level |
| start_date | TIMESTAMP | | Start date and time of the admission |
| end_date | TIMESTAMP | | End date and time of the admission |
| load_date | TIMESTAMP | | Date of update |
| care_level_type_ref | VARCHAR(16) | FK | Care level type: **WARD** (conventional hospitalization), **ICU** (intensive care unit), **EM** (emergency episode), **SPEC** (special episode), **HAH** (hospital at home), **PEND. CLAS** (pending classification), **SHORT** (short stay) |

**Example (5 rows)**

| patient_ref | episode_ref | care_level_ref | start_date | end_date | load_date | care_level_type_ref |
| --- | --- | --- | --- | --- | --- | --- |
| 900001 | 900002 | 16 | 2099-01-03 18:33:07 | 2099-01-03 11:12:57 | 2099-01-03 18:22:13 | EM |
| 900003 | 900004 | 17 | 2099-01-04 07:30:00 | 2099-01-04 11:02:48 | 2099-01-04 22:04:44 | WARD |
| 900005 | 900006 | 18 | 2099-01-05 16:00:00 | 2099-01-05 15:40:00 | 2099-01-05 11:18:20 | WARD |
| 900007 | 900008 | 19 | 2099-01-06 08:15:00 | 2099-01-06 14:27:31 | 2099-01-06 11:18:56 | SHORT |
| 900009 | 900010 | 20 | 2099-01-07 23:00:00 | 2099-01-07 11:38:33 | 2099-01-07 11:19:08 | EM |


---

### movements

Contains the movements for each care level. Movements are changes in the patient's location. Patient discharge and exitus are also considered movements. All movements have a `care_level_ref`. Only EM, HAH and all HOSP (HOSP, HOSP_RN and HOSP_IQ) episode types have movements.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| start_date | TIMESTAMP | | Date and time of the start of the movement |
| end_date | TIMESTAMP | | Date and time of the end of the movement |
| place_ref | BIGINT | | Encrypted reference for the patient's room and bed |
| ou_med_ref | VARCHAR(8) | FK | Medical organizational unit reference |
| ou_med_descr | VARCHAR(32) | | Description of the medical organizational unit reference |
| ou_loc_ref | VARCHAR(8) | FK | Physical hospitalization unit reference |
| ou_loc_descr | VARCHAR(32) | | Description of the physical hospitalization unit reference |
| care_level_type_ref | VARCHAR | FK | Care level (ICU, HAH, etc.) |
| facility | VARCHAR(32) | | Description of the facility reference |
| load_date | TIMESTAMP | | Date of update |
| care_level_ref | INT | FK | Unique identifier that groups care levels (intensive care unit, conventional hospitalization, etc.) if they are consecutive and belong to the same level |

**Example (5 rows)**

| patient_ref | episode_ref | start_date | end_date | place_ref | ou_med_ref | ou_med_descr | ou_loc_ref | ou_loc_descr | care_level_type_ref | facility | load_date | care_level_ref |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900011 | 900012 | 2099-01-03 12:20:16 | 2099-01-03 13:52:46 | 900013 | HDM | Example unit | UNIT_X | Example unit | HAH | Example facility | 2099-01-04 08:55:14 | 546 |
| 900011 | 900012 | 2099-01-05 13:52:46 | 2099-01-05 14:07:24 | 900014 | HDM | Example unit | UNIT_X | Example unit | HAH | Example facility | 2099-01-06 08:55:14 | 546 |
| 900015 | 100006 | 2099-01-07 13:49:11 | 2099-01-07 14:04:38 | 900017 | HDM | Example unit | UNIT_X | Example unit | HAH | Example facility | 2099-01-08 08:55:14 | 900018 |
| 900019 | 100010 | 2099-01-09 18:18:54 | 2099-01-09 14:36:45 | 900021 | HDM | Example unit | UNIT_X | Example unit | HAH | Example facility | 2099-01-10 08:55:14 | 900022 |
| 900019 | 100010 | 2099-01-11 14:36:45 | 2099-01-11 14:36:45 | 900021 | HDM | Example unit | UNIT_X | Example unit | HAH | Example facility | 2099-01-12 11:17:41 | 900022 |


---

### demographics

Contains demographic information for each patient.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | PK | Pseudonymized number that identifies a patient |
| birth_date | DATE | | Date of birth |
| sex | INT | | Sex: **-1** (not reported in SAP), **1** (male), **2** (female), **3** (other) |
| natio_ref | VARCHAR(8) | FK | Reference code for nationality |
| natio_descr | VARCHAR(512) | | Description of the country code according to ISO:3 |
| health_area | VARCHAR | | Health area |
| postcode | VARCHAR | | Postal code |
| load_date | TIMESTAMP | | Date of update |

**Example (5 rows)**

| patient_ref | birth_date | sex | natio_ref | natio_descr | health_area | postcode | load_date |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 900023 | 2090-01-01 | 1 | XX | Example country | AREA_A | 00000 | 2099-12-31 12:00:00 |
| 900025 | 2090-01-02 | 1 | XX | Example country | AREA_A | 00000 | 2099-12-31 12:00:00 |
| 900027 | 2090-01-03 | 1 | XX | Example country | AREA_A | 00000 | 2099-12-31 12:00:00 |
| 900029 | 2090-01-04 | 2 | XX | Example country | AREA_A | 00000 | 2099-12-31 12:00:00 |
| 900031 | 2090-01-05 | 2 | XX | Example country | AREA_A | 00000 | 2099-12-31 12:00:00 |


---

### exitus

Contains the date of death for each patient.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | PK | Pseudonymized number that identifies a patient |
| exitus_date | DATE | | Date of death |
| load_date | TIMESTAMP | | Date and time of update |

**Example (5 rows)**

| patient_ref | exitus_date | load_date |
| --- | --- | --- |
| 900001 | 2099-01-03 | 2099-12-31 12:00:00 |
| 900002 | 2099-01-04 | 2099-12-31 12:00:00 |
| 900003 | 2099-01-05 | 2099-12-31 12:00:00 |
| 900004 | 2099-01-06 | 2099-12-31 12:00:00 |
| 900005 | 2099-01-07 | 2099-12-31 12:00:00 |


---

### adm_disch

Contains the reasons for admission and discharge per episode.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| mot_ref | INT | FK | Reason for admission or discharge (numeric) |
| mot_descr | VARCHAR(32) | | Description of the mot_ref |
| mot_type | VARCHAR(45) | | Indicates whether it is the starting motive (**ST**) or ending motive (**END**) of the episode |
| load_date | TIMESTAMP | | Update date |

**Example (5 rows)**

| patient_ref | episode_ref | mot_ref | mot_descr | mot_type | load_date |
| --- | --- | --- | --- | --- | --- |
| 900033 | 900034 | 900035 | Example motive | START | 2099-01-03 06:03:39 |
| 900036 | 900037 | 900035 | Example motive | START | 2099-01-04 23:31:25 |
| 900038 | 900039 | 900035 | Example motive | START | 2099-01-05 13:38:39 |
| 900040 | 900041 | 900035 | Example motive | START | 2099-01-06 23:50:44 |
| 900042 | 900043 | 900035 | Example motive | START | 2099-01-07 21:05:23 |


---

### diagnostics

Contains information about the diagnoses for each episode.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| diag_date | TIMESTAMP | | Diagnostic code registration date |
| diag_ref | INT | FK | DataNex own diagnosis reference number |
| catalog | INT | | Catalog to which the 'code' belongs: **1** (CIE9 MC, until 2017), **2** (MDC), **3** (CIE9 Emergencies), **4** (ACR), **5** (SNOMED), **7** (MDC-AP), **8** (SNOMEDCT), **9** (Subset ANP SNOMED CT), **10** (Subset ANP SNOMED ID), **11** (CIE9 in Outpatients), **12** (CIE10 MC), **13** (CIE10 Outpatients) |
| code | VARCHAR | | ICD-9 or ICD-10 code for each diagnosis |
| diag_descr | VARCHAR(32) | | Description of the diagnosis |
| class | VARCHAR(2) | | Diagnosis class: **P** (primary diagnosis validated by documentalist), **S** (secondary diagnosis validated by documentalist), **H** (diagnosis not validated by documentalist), **E** (emergency diagnosis), **A** (outpatient diagnosis). A hospitalization episode has only one P diagnosis and zero or more S or H diagnoses |
| poa | VARCHAR(2) | | Present on Admission indicator: **Y** (present at admission - comorbidity), **N** (not present at admission - complication), **U** (unknown - insufficient documentation), **W** (clinically undetermined), **E** (exempt), **-** (unreported - documentalist has not registered the diagnostic code) |
| load_date | TIMESTAMP | | Date of update |

> ⚠️ **Searching diagnoses**: There is no diagnostics dictionary table. Search this table directly using `code` (ICD-9 / ICD-10) with `LIKE`, or `diag_descr` with `LIKE`. Do not try to join `diag_ref` against any external dictionary — none exists.

**Example (5 rows)**

| patient_ref | episode_ref | diag_date | diag_ref | catalog | code | diag_descr | class | poa | load_date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900044 | 100005 | 2099-01-03 11:48:31 | 1 | 12 | M15.4 | (osteo)artrosis erosiva | A | - | 2099-01-03 09:50:42 |
| 900046 | 100007 | 2099-01-04 08:39:17 | 1 | 12 | M15.4 | (osteo)artrosis erosiva | A | - | 2099-01-04 13:07:18 |
| 900048 | 100009 | 2099-01-05 17:45:34 | 1 | 12 | M15.4 | (osteo)artrosis erosiva | A | - | 2099-01-05 09:50:42 |
| 900050 | 100001 | 2099-01-06 09:52:19 | 1 | 12 | M15.4 | (osteo)artrosis erosiva | A | - | 2099-01-06 08:36:37 |
| 900052 | 100003 | 2099-01-07 19:30:48 | 1 | 12 | M15.4 | (osteo)artrosis erosiva | A | - | 2099-01-07 08:36:37 |


---

### diagnostic_related_groups

Contains the Diagnosis-Related-Groups (DRG). DRG is a concept used to categorize hospital cases into groups according to diagnosis, procedures, age, comorbidities and other factors. These DRG are used mainly for administrative purposes, billing and resource allocation. DRG are further classified in Major Diagnostic Categories (MDC).

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| weight | DOUBLE | | DRG cost weight - relative resource consumption for that group compared to others |
| drg_ref | INT | FK | DRG (Diagnosis-Related Group) reference |
| severity_ref | VARCHAR(2) | FK | SOI (Severity of Illness) reference - metric to evaluate how sick a patient is |
| severity_descr | VARCHAR(128) | | Description of the SOI reference |
| mortality_risk_ref | VARCHAR(2) | FK | ROM (Risk of Mortality) reference - metric to evaluate likelihood of patient dying |
| mortality_risk_descr | VARCHAR(128) | | Description of the ROM reference |
| mdc_ref | VARCHAR | FK | MDC (Major Diagnostic Categories) reference - broad categories used to group DRG based on similar clinical conditions or body systems |
| load_date | TIMESTAMP | | Date of update |

**Example (5 rows)**

| patient_ref | episode_ref | weight | drg_ref | severity_ref | severity_descr | mortality_risk_ref | mortality_risk_descr | mdc_ref | load_date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 343 | 181 | 0.3292 | 560 | 2 | Moderate | 1 | Minor | 14 | 2099-01-03 11:48:19 |
| 473 | 220 | 0.5545 | 750 | 1 | Minor | 1 | Minor | 19 | 2099-01-04 11:48:19 |
| 604 | 286 | 0.4554 | 751 | 2 | Moderate | 1 | Minor | 19 | 2099-01-05 11:48:19 |
| 740 | 350 | 0.3292 | 560 | 2 | Moderate | 1 | Minor | 14 | 2099-01-06 11:48:19 |
| 771 | 365 | 0.4932 | 540 | 1 | Minor | 1 | Minor | 14 | 2099-01-07 11:48:19 |


---

### health_issues

Contains information about all health problems related to a patient. Health problems are SNOMED-CT (Systematized Nomenclature of Medicine Clinical Terms) codified health problems that a patient may present. SNOMED is a comprehensive multilingual clinical terminology used worldwide in healthcare. These health problems are codified by the doctors taking care of the patients, expanding the codification possibilities.

Health problems have a start date (when first recorded by the clinician) and may also have an end date (when the clinician determined the problem was no longer active).

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| snomed_ref | BIGINT | | SNOMED code for a health problem |
| snomed_descr | VARCHAR(255) | | Description of the SNOMED code |
| ou_med_ref | VARCHAR(8) | FK | Medical organizational unit reference |
| start_date | TIMESTAMP | | Start date of the health problem |
| end_date | TIMESTAMP | | End date of the health problem (not mandatory) |
| end_motive | VARCHAR | | Reason for the change (not mandatory) |
| load_date | TIMESTAMP | | Date of update |

**Example (5 rows)**

| patient_ref | episode_ref | snomed_ref | snomed_descr | ou_med_ref | start_date | end_date | end_motive | load_date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900054 | 900055 | 100006 |  | UCOT | 2099-01-03 00:00:00 |  | 03 | 2099-01-03 15:32:56 |
| 900057 | 900058 | 100006 |  | UCOT | 2099-01-04 00:00:00 |  | 03 | 2099-01-04 15:30:09 |
| 900059 | 900060 | 100006 |  | UCOT | 2099-01-05 00:00:00 |  | 03 | 2099-01-05 15:30:42 |
| 900061 |  | 900062 |  | CAR | 2099-01-06 00:00:00 |  | 03 | 2099-01-06 15:25:04 |
| 900063 |  | 900064 |  | URM | 2099-01-07 00:00:00 |  | 03 | 2099-01-07 15:26:12 |


---

### labs

Contains the laboratory tests for each episode.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| extrac_date | TIMESTAMP | | Date and time the sample was extracted |
| result_date | TIMESTAMP | | Date and time the result was obtained |
| load_date | TIMESTAMP | | Date of update |
| ou_med_ref | VARCHAR(8) | FK | Medical organizational unit |
| care_level_ref | INT | FK | Unique identifier that groups care levels (ICU, WARD, etc.) if they are consecutive and belong to the same level; the care_level_ref is absent if the lab test is requested after the end of the episode in EM, HOSP and HAH episodes |
| lab_sap_ref | VARCHAR(16) | FK | SAP laboratory parameter reference |
| lab_descr | VARCHAR(32) | | lab_sap_ref description |
| result_num | DOUBLE | | Numerical result of the laboratory test |
| result_txt | VARCHAR(128) | | Text result from the DataNex laboratory reference |
| units | VARCHAR(32) | | Units |
| lab_group_ref | VARCHAR | | Reference for grouped laboratory parameters |

**Example (5 rows)**

| patient_ref | episode_ref | extrac_date | result_date | load_date | ou_med_ref | care_level_ref | lab_sap_ref | lab_descr | result_num | result_txt | units | lab_group_ref |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6835 | 5416 | 2099-01-03 11:09:30 | 2099-01-03 17:33:55 | 2099-01-03 13:05:02 | GAS |  | LAB0SDHF | Example lab parameter |  | (Example result) | N.D. | 900065 |
| 6835 | 5416 | 2099-01-04 11:09:30 | 2099-01-04 09:11:03 | 2099-01-04 13:05:02 | GAS |  | LAB0SDHF | Example lab parameter |  | (Example result) | N.D. | 900065 |
| 900066 | 100007 | 2099-01-05 07:40:22 | 2099-01-05 18:45:20 | 2099-01-05 20:19:46 | END |  | LAB0SDHF | Example lab parameter |  | (Example result) | N.D. | 900065 |
| 900068 | 100009 | 2099-01-06 16:18:10 | 2099-01-06 13:29:53 | 2099-01-06 09:14:46 | END |  | LAB0SDHF | Example lab parameter |  | (Example result) | N.D. | 900065 |
| 900070 | 900071 | 2099-01-07 09:58:40 | 2099-01-07 11:14:20 | 2099-01-07 12:52:26 | END |  | LAB0SDHF | Example lab parameter |  | Example result | N.D. | 900065 |


---

### dic_lab_loinc

Lookup table that maps each SAP laboratory parameter (`lab_sap_ref`) to its LOINC code and canonical units. This is the **only `dic_*` dictionary table that survived the AWS migration**; all other historical dictionaries (`dic_lab`, `dic_rc`, `dic_ou_med`, `dic_ou_loc`, `dic_diagnostic`, `dic_rc_text`) were removed.

Use it when the user asks for the LOINC equivalent of a lab parameter, or when consolidating lab results across systems that index by LOINC instead of by SAP code. For plain code↔description lookups inside the hospital, `labs.lab_sap_ref` + `labs.lab_descr` is usually enough; reach for `dic_lab_loinc` when LOINC is the goal.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| lab_sap_ref | VARCHAR | PK | SAP laboratory parameter reference; joins to `labs.lab_sap_ref` |
| lab_descr | VARCHAR | | Description of the lab parameter |
| units | VARCHAR | | Canonical units for the parameter |
| loinc_code | VARCHAR | | LOINC code mapped to `lab_sap_ref` |

**Example (5 rows)**

| lab_sap_ref | lab_descr | units | loinc_code |
| --- | --- | --- | --- |
| LAB90001 | Example lab parameter | N.D. | 90001-0 |
| LAB90002 | Example lab parameter | mg/dL | 90002-0 |
| LAB90003 | Example lab parameter | seg | 90003-0 |
| LAB90004 | Example lab parameter | seg | 90004-0 |
| LAB90005 | Example lab parameter | g/L | 90005-0 |


---

### rc

Contains the clinical records for each episode.

> ⚠️ **CRITICAL JOIN RULE**: `episode_ref` and `care_level_ref` are currently **NULL for every row** in this table (ETL backfill pending). **Do NOT join `rc` with any other table via `episode_ref` or `care_level_ref`** — the join will silently return zero rows. **Always join `rc` via `patient_ref`**, and restrict to the relevant episode or stay using a **temporal window** on `result_date` (e.g. `rc.result_date BETWEEN cohort.start_date AND cohort.end_date`). See the "Joining tables" rules at the top of this document for the exact pattern.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| result_date | TIMESTAMP | | Date and time of the measurement |
| meas_type_ref | VARCHAR | | Measurement type: **0** (manual input), **1** (from machine, result not validated), **2** (from machine, result validated) |
| ou_loc_ref | VARCHAR(8) | FK | Physical hospitalization unit; filled if the clinical registry is manually collected, empty if automatically collected |
| ou_med_ref | VARCHAR(8) | FK | Medical organizational unit; filled if the clinical registry is manually collected, empty if automatically collected |
| rc_sap_ref | VARCHAR(16) | | SAP clinical record reference |
| rc_descr | VARCHAR(32) | | Description of the SAP clinical record reference |
| result_num | DOUBLE | | Numerical result of the clinical record |
| result_txt | VARCHAR(128) | | Text result from the DataNex clinical record reference |
| units | VARCHAR | | Units |
| care_level_ref | INT | FK | Unique identifier that groups care levels (intensive care unit, conventional hospitalization, etc.) if they are consecutive and belong to the same level |
| load_date | TIMESTAMP | | Date of update |

**Example (5 rows)**

| patient_ref | episode_ref | result_date | meas_type_ref | ou_loc_ref | ou_med_ref | rc_sap_ref | rc_descr | result_num | result_txt | units | care_level_ref | load_date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900072 |  | 2099-01-03 09:00:00 | 0 | GEL2 | OBS | ABDOMEN_DIST | Distensión abdominal |  | EXAMPLE_CODE | Descripción |  | 2099-01-03 19:26:32 |
| 900073 |  | 2099-01-04 09:00:00 | 0 | GEL2 | OBS | ABDOMEN_DIST | Distensión abdominal |  | EXAMPLE_CODE | Descripción |  | 2099-01-04 19:26:32 |
| 900074 |  | 2099-01-05 11:00:00 | 0 | SP00 | OBS | ABDOMEN_DIST | Distensión abdominal |  | EXAMPLE_CODE | Descripción |  | 2099-01-05 20:06:22 |
| 900075 |  | 2099-01-06 10:00:00 | 0 | GEL2 | OBS | ABDOMEN_DIST | Distensión abdominal |  | EXAMPLE_CODE | Descripción |  | 2099-01-06 20:56:43 |
| 900076 |  | 2099-01-07 10:00:00 | 0 | GEL2 | OBS | ABDOMEN_DIST | Distensión abdominal |  | EXAMPLE_CODE | Descripción |  | 2099-01-07 20:06:22 |


---

### micro

Contains the microbiology results for each episode.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| extrac_date | TIMESTAMP | | Date and time the sample was extracted |
| res_date | TIMESTAMP | | Date and time the result was obtained |
| ou_med_ref | VARCHAR(8) | FK | Medical organizational unit |
| mue_ref | VARCHAR | | Code that identifies the type or origin of the sample |
| mue_descr | VARCHAR | | Description of the type or origin of the sample; provides a general classification of the sample |
| method_descr | VARCHAR | | Detailed description of the sample itself or the method used to process it |
| positive | VARCHAR | | 'X' means that a microorganism has been detected in the sample |
| antibiogram_ref | VARCHAR | FK | Unique identifier for the antibiogram (joins to `antibiograms.antibiogram_ref`) |
| micro_ref | VARCHAR | | Code that identifies the microorganism |
| micro_descr | VARCHAR | | Scientific name of the microorganism |
| num_micro | INT | | Number that starts at 1 for the first identified microbe and increments by 1 for each newly identified microbe in the sample |
| result_text | VARCHAR(128) | | Text result from the microbiology sample |
| load_date | TIMESTAMP | | Date of update |
| care_level_ref | INT | FK | Unique identifier that groups care levels (intensive care unit, conventional hospitalization, etc.) if they are consecutive and belong to the same level |

**Example (5 rows)**

| patient_ref | episode_ref | extrac_date | res_date | ou_med_ref | mue_ref | mue_descr | method_descr | positive | antibiogram_ref | micro_ref | micro_descr | num_micro | result_text | load_date | care_level_ref |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900077 | 900078 | 2099-01-03 13:41:00 | 2099-01-03 08:58:47 | HEP | MICMAEX | Aspirats, Exudats, Biópsies, Drenatges | Biopsia |  |  |  |  |  |  Negative,  | 2099-01-03 12:18:29 |  |
| 900079 | 900080 | 2099-01-04 15:05:00 | 2099-01-04 09:33:13 | URM | MICMAEX | Aspirats, Exudats, Biópsies, Drenatges | Abscés/pus/exudat | X | 900081 | MICSAUR | Staphylococcus aureus | 1.0 |  Surten abundants colònies de: Staphylococcus aureus | 2099-01-04 12:23:31 |  |
| 900082 | 900083 | 2099-01-05 19:27:00 | 2099-01-05 15:20:25 | MDI | MICMAEX | Aspirats, Exudats, Biópsies, Drenatges | Abscés/pus/exudat |  |  |  |  |  |  Sample not received,  | 2099-01-05 12:23:31 |  |
| 900084 | 900085 | 2099-01-06 11:38:00 | 2099-01-06 09:10:03 | GER | MICMAEX | Aspirats, Exudats, Biópsies, Drenatges | Abscés/pus/exudat | X | 900086 | MICECOL | Escherichia coli | 1.0 |  Surten abundants colònies de: Escherichia coli | 2099-01-06 12:33:43 |  |
| 900087 | 900088 | 2099-01-07 12:51:00 | 2099-01-07 19:21:39 | ERM | MICMAEX | Aspirats, Exudats, Biópsies, Drenatges | Abscés/pus/exudat | X | 900089 | MICECNE | Estafilococ coagulasa Negative | 1.0 |  Surten abundants colònies de: Estafilococ coagulasa Negative | 2099-01-07 12:33:43 |  |


---

### antibiograms

Contains the antibiograms for each episode.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| extrac_date | TIMESTAMP | | Date and time the sample was extracted |
| result_date | TIMESTAMP | | Date and time the result was obtained |
| sample_ref | VARCHAR | | Code that identifies the type or origin of the sample |
| sample_descr | VARCHAR | | Description of the type or origin of the sample; provides a general classification of the sample |
| antibiogram_ref | VARCHAR | | Unique identifier for the antibiogram |
| micro_ref | VARCHAR | | Code that identifies the microorganism |
| micro_descr | VARCHAR | | Scientific name of the microorganism |
| antibiotic_ref | VARCHAR | | Code of the antibiotic used in the sensitivity testing |
| antibiotic_descr | VARCHAR | | Full name of the antibiotic |
| result | VARCHAR | | Result of the antibiotic sensitivity test; represents the minimum inhibitory concentration (MIC) required to inhibit the growth of the bacteria |
| sensitivity | VARCHAR | | Sensitivity (**S**) or resistance (**R**) of the bacteria to the antibiotic tested |
| load_date | TIMESTAMP | | Date of update |
| care_level_ref | INT | FK | Unique identifier that groups care levels (intensive care unit, conventional hospitalization, etc.) if they are consecutive and belong to the same level |

**Example (5 rows)**

| patient_ref | episode_ref | extrac_date | result_date | sample_ref | sample_descr | antibiogram_ref | micro_ref | micro_descr | antibiotic_ref | antibiotic_descr | result | sensitivity | load_date | care_level_ref |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900090 | 900091 | 2099-01-03 14:30:00 | 2099-01-03 09:17:35 | MICMPFA | Teixit epitelial, dermis | 900092 | MICSAUR | Staphylococcus aureus | MICFUS | Acid Fusidic | <=0,5 | S | 2099-01-03 12:33:43 |  |
| 900093 | 900094 | 2099-01-04 20:09:00 | 2099-01-04 10:00:35 | MICMPFA | Teixit epitelial, dermis | 900095 | MICSAUR | Staphylococcus aureus | MICFUS | Acid Fusidic | 1 | S | 2099-01-04 12:48:05 |  |
| 900096 | 900097 | 2099-01-05 20:18:00 | 2099-01-05 09:09:10 | MICMPFA | Teixit epitelial, dermis | 900098 | MICSAUR | Staphylococcus aureus | MICFUS | Acid Fusidic | <=0,5 | S | 2099-01-05 13:02:19 |  |
| 900099 | 900100 | 2099-01-06 05:14:00 | 2099-01-06 17:01:49 | MICMPFA | Teixit epitelial, dermis | 900001 | MICSAUR | Staphylococcus aureus | MICFUS | Acid Fusidic | 1 | S | 2099-01-06 13:07:05 |  |
| 900002 | 900003 | 2099-01-07 17:23:00 | 2099-01-07 16:32:45 | MICMMOS | Material osteoarticular | 900004 | MICSAUR | Staphylococcus aureus | MICFUS | Acid Fusidic | 1 | S | 2099-01-07 13:16:17 |  |


---

### prescriptions

Contains the prescribed medical products (pharmaceuticals and medical devices) for each episode. A treatment prescription (identified by `treatment_ref`) may be composed by one or more medical products, so this table will show as many rows as prescribed medical products per treatment prescription.

The `treatment_ref` field serves as a foreign key that links the `prescriptions`, `administrations` and `perfusions` tables.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| treatment_ref | INT | | Code that identifies a treatment prescription |
| prn | VARCHAR | | Null value or "X"; the "X" indicates that this drug is administered only if needed |
| freq_ref | VARCHAR | FK | Administration frequency code |
| phform_ref | INT | FK | Pharmaceutical form identifier |
| phform_descr | VARCHAR | | Description of phform_ref |
| prescr_env_ref | INT | FK | Healthcare setting where the prescription was generated (see complementary descriptions) |
| adm_route_ref | INT | FK | Administration route reference |
| route_descr | VARCHAR | | Description of adm_route_ref |
| atc_ref | VARCHAR | | ATC code |
| atc_descr | VARCHAR | | Description of the ATC code |
| ou_loc_ref | VARCHAR(8) | FK | Physical hospitalization unit |
| ou_med_ref | VARCHAR(8) | FK | Medical organizational unit |
| start_drug_date | TIMESTAMP | | Start date of prescription validity |
| end_drug_date | TIMESTAMP | | End date of prescription validity |
| load_date | TIMESTAMP | | Date of update |
| drug_ref | VARCHAR | FK | Medical product identifier |
| drug_descr | VARCHAR | | Description of the drug_ref field |
| enum | VARCHAR | | Role of the drug in the prescription (see complementary descriptions where `enum` equals `drug_type_ref`) |
| dose | REAL | | Prescribed dose |
| unit | VARCHAR | FK | Dose unit (see complementary descriptions) |
| care_level_ref | INT | FK | Unique identifier that groups care levels (ICU, WARD, etc.) if they are consecutive and belong to the same level |


**Example (5 rows)**

| patient_ref | episode_ref | treatment_ref | prn | freq_ref | phform_ref | phform_descr | prescr_env_ref | adm_route_ref | route_descr | atc_ref | atc_descr | ou_loc_ref | ou_med_ref | start_drug_date | end_drug_date | load_date | drug_ref | drug_descr | enum | dose | unit | care_level_ref |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4923 | 100005 | 100006 |  | DE-0-0 | 110 | CAPSULA | 4 | 100 | ORAL | A02BC01 | Omeprazol | G093 | HEP | 2099-01-03 15:28:22 | 2099-01-03 15:29:25 | 2099-01-03 13:51:50 | DRUGREF001 | OMEPRAZOL | 0 | 1.0 | UND |  |
| 4923 | 100005 | 100007 |  | DE-0-0 | 110 | CAPSULA | 4 | 100 | ORAL | A02BC01 | Omeprazol | G093 | HEP | 2099-01-04 15:29:20 | 2099-01-04 19:26:10 | 2099-01-04 14:26:27 | DRUGREF001 | OMEPRAZOL | 0 | 1.0 | UND |  |
| 900008 | 100009 | 100010 |  | C/12H | 110 | CAPSULA | 4 | 100 | ORAL | A02BC01 | Omeprazol | U071 | HEM | 2099-01-05 13:48:41 | 2099-01-05 19:16:46 | 2099-01-05 14:55:54 | DRUGREF001 | OMEPRAZOL | 0 | 1.0 | UND |  |
| 900011 | 100002 | 100003 |  | C/24H | 110 | CAPSULA | 4 | 100 | ORAL | A02BC01 | Omeprazol | G093 | HEP | 2099-01-06 10:12:29 | 2099-01-06 10:12:48 | 2099-01-06 13:51:50 | DRUGREF001 | OMEPRAZOL | 0 | 1.0 | UND |  |
| 900011 | 100002 | 100004 |  | C/24H | 110 | CAPSULA | 4 | 100 | ORAL | A02BC01 | Omeprazol | G093 | HEP | 2099-01-07 10:12:43 | 2099-01-07 19:28:14 | 2099-01-07 14:26:27 | DRUGREF001 | OMEPRAZOL | 0 | 1.0 | UND |  |


---

### administrations

Contains the administered pharmaceuticals (drugs) for each episode. The `treatment_ref` field serves as a foreign key that links the `prescriptions`, `administrations` and `perfusions` tables.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| treatment_ref | INT | | Code that identifies a treatment prescription |
| administration_date | TIMESTAMP | | Date and time of administration |
| route_ref | INT | FK | Administration route reference |
| route_descr | VARCHAR | | Description of route_ref |
| prn | VARCHAR | | Null value or "X"; the "X" indicates that this drug is administered only if needed |
| given | VARCHAR | | Null value or "X"; the "X" indicates that this drug has not been administered |
| not_given_reason_ref | INT | | Number that indicates the reason for non-administration |
| drug_ref | VARCHAR | FK | Medical product identifier |
| drug_descr | VARCHAR | | Description of the drug_ref field |
| atc_ref | VARCHAR | | ATC code |
| atc_descr | VARCHAR | | Description of the ATC code |
| enum | INT | | Role of the drug in the prescription (see complementary descriptions where `enum` equals `drug_type_ref`) |
| quantity | REAL | | Dose actually administered to the patient |
| quantity_planing | REAL | | Planned dose |
| quantity_unit | VARCHAR | FK | Dose unit (see complementary descriptions) |
| load_date | TIMESTAMP | | Date of update |
| care_level_ref | INT | FK | Unique identifier that groups care levels (ICU, WARD, etc.) if they are consecutive and belong to the same level |


**Example (5 rows)**

| patient_ref | episode_ref | treatment_ref | administration_date | route_ref | route_descr | prn | given | not_given_reason_ref | drug_ref | drug_descr | atc_ref | atc_descr | enum | quantity | quantity_planing | quantity_unit | load_date | care_level_ref |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900015 | 100006 | 900017 | 2099-01-03 13:46:00 | 350 | PERFUSION INTRAVENOSA |  |  | 0 | DRUGREF001 | DOPAMINA [x8] 2000 MG + SF / 250 ML | B05BB91 | Sodio cloruro, solucion parenteral | 0 | 250.0 |  | ML | 2099-01-03 12:34:41 |  |
| 900015 | 100006 | 900017 | 2099-01-04 00:00:00 | 350 | PERFUSION INTRAVENOSA |  |  | 0 | DRUGREF001 | DOPAMINA [x8] 2000 MG + SF / 250 ML | B05BB91 | Sodio cloruro, solucion parenteral | 0 | 250.0 |  | ML | 2099-01-04 12:34:41 |  |
| 900018 | 100009 | 900020 | 2099-01-05 15:48:48 | 100 | ORAL |  | X | 7 | DRUGREF001 | CITALOPRAM, 30 MG COMP | N06AB04 | Citalopram | 0 | 1.0 |  | UND | 2099-01-05 13:06:02 |  |
| 900018 | 100009 | 900020 | 2099-01-06 16:09:33 | 100 | ORAL |  | X | 7 | DRUGREF001 | CITALOPRAM, 30 MG COMP | N06AB04 | Citalopram | 0 | 1.0 |  | UND | 2099-01-06 13:06:02 |  |
| 900018 | 100009 | 900020 | 2099-01-07 16:39:56 | 100 | ORAL |  | X | 7 | DRUGREF001 | CITALOPRAM, 30 MG COMP | N06AB04 | Citalopram | 0 | 1.0 |  | UND | 2099-01-07 13:06:02 |  |


---

### perfusions

Contains data about the administered drug perfusions for each episode. The `treatment_ref` field serves as a foreign key that links the `prescriptions`, `administrations` and `perfusions` tables.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| treatment_ref | INT | | Code that identifies a treatment prescription. Points to the `treatment_ref` in the `administrations` and `prescriptions` tables |
| infusion_rate | REAL | | Rate in ml/h |
| rate_change_counter | INT | | Perfusion rate change counter: starts at 1 (first rate) and increments by one unit with each change (each new rate) |
| start_date | TIMESTAMP | | Start date of the perfusion |
| end_date | TIMESTAMP | | End date of the perfusion |
| load_date | TIMESTAMP | | Date of update |
| care_level_ref | INT | FK | Unique identifier that groups care levels (ICU, WARD, etc.) if they are consecutive and belong to the same level |

**Example (5 rows)**

| patient_ref | episode_ref | treatment_ref | infusion_rate | rate_change_counter | start_date | end_date | load_date | care_level_ref |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900021 | 100002 | 100003 | 41.67 | 1 | 2099-01-03 00:17:00 | 2099-01-03 09:00:00 | 2099-01-03 09:50:12 |  |
| 900021 | 100002 | 100003 | 41.67 | 2 | 2099-01-04 09:00:00 | 2099-01-04 19:55:00 | 2099-01-04 09:50:12 |  |
| 900021 | 100002 | 100003 | 41.67 | 3 | 2099-01-05 19:55:00 | 2099-01-05 21:00:00 | 2099-01-05 09:50:12 |  |
| 900021 | 100002 | 100004 | 62.5 | 1 | 2099-01-06 00:17:00 | 2099-01-06 01:00:00 | 2099-01-06 09:50:12 |  |
| 900021 | 100002 | 100004 | 62.5 | 2 | 2099-01-07 01:00:00 | 2099-01-07 09:00:00 | 2099-01-07 09:50:12 |  |


---

### encounters

An encounter refers to a punctual event in which detailed information is recorded about a medical interaction or procedure involving a patient (for instance a chest radiograph, an outpatient visit, etc.).

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| date | TIMESTAMP | | Date of the encounter event |
| load_date | TIMESTAMP | | Update date |
| ou_med_ref | VARCHAR(8) | FK | Medical organizational unit reference (look up the description via a helper query on `movements.ou_med_ref` / `ou_med_descr`) |
| ou_loc_ref | VARCHAR(8) | FK | Physical hospitalization unit reference (look up the description via a helper query on `movements.ou_loc_ref` / `ou_loc_descr`) |
| encounter_type | VARCHAR(8) | FK | Encounter type (see dictionary below) |
| agen_ref | VARCHAR | FK | Code that identifies the encounter |
| act_type_ref | VARCHAR(8) | FK | Activity type |

**Encounter type dictionary:**

| Code | Description |
|------|-------------|
| 2O | 2ª opinión |
| AD | Hosp. día domic. |
| BO | Blog. obstétrico |
| CA | Cirugía mayor A |
| CM | Cirugía menor A |
| CU | Cura |
| DH | Derivación hosp |
| DI | Der. otros serv. |
| DU | Derivación urg. |
| EI | Entrega ICML |
| HD | Hospital de día |
| IC | Interconsulta |
| IH | Servicio final |
| IQ | Interv. quir. |
| LT | Llamada telef. |
| MA | Copia mater. |
| MO | Morgue |
| NE | Necropsia |
| PA | Preanestesia |
| PD | Posible donante |
| PF | Pompas fúnebres |
| PP | Previa prueba |
| PR | Prueba |
| PV | Primera vista |
| RE | Recetas |
| SM | Sec. multicentro |
| TR | Tratamiento |
| UD | Urg. hosp. día |
| UR | Urgencias |
| VD | Vis. domicilio |
| VE | V. Enf. Hospital |
| VS | Vista sucesiva |
| VU | Vista URPA / Vista urgencias |

> ⚠️ **Note**: The dictionaries for `agen_ref` and `act_type_ref` fields will be available in future updates.

**Example (5 rows)**

| patient_ref | episode_ref | date | load_date | ou_med_ref | ou_loc_ref | encounter_type | agen_ref | act_type_ref |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900001 | 800001 | 2099-01-03 12:33:59 | 2099-12-31 12:00:00 | ONC | ONCAC | HD | UAC | FIMP |
| 900001 | 800002 | 2099-01-04 08:45:02 | 2099-12-31 12:00:00 | NRC | NRCCE | PP |  |  |
| 900001 | 800002 | 2099-01-05 09:45:00 | 2099-12-31 12:00:00 | NRC | NRCCE | IC |  |  |
| 900001 | 800002 | 2099-01-06 21:17:00 | 2099-12-31 12:00:00 | RADIO | SCA | PR | TCP1 | CNRL |
| 900001 | 800002 | 2099-01-07 10:15:00 | 2099-12-31 12:00:00 | NRC | NRCCE | VS |  |  |


---

### procedures

Contains all procedures per episode.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| ou_loc_ref | VARCHAR(8) | FK | Physical hospitalization unit |
| ou_med_ref | VARCHAR(8) | FK | Medical organizational unit |
| catalog | VARCHAR(10) | | Catalog: **1** (ICD9), **12** (ICD10) |
| code | VARCHAR(10) | | Procedure code |
| descr | VARCHAR(255) | | Procedure description |
| text | VARCHAR(255) | | Details about the procedure |
| place_ref | VARCHAR | | Location of the procedure (code): **1** (Bloque quirúrgico), **2** (Gabinete diagnóstico y terapéutico), **3** (Cirugía menor), **4** (Radiología intervencionista o medicina nuclear), **5** (Sala de no intervención), **6** (Bloque obstétrico), **EX** (Procedimiento externo) |
| place_descr | VARCHAR | | Description of `place_ref` |
| class | VARCHAR(2) | | Procedure class: **P** (primary procedure), **S** (secondary procedure) |
| start_date | TIMESTAMP | | Start date of the procedure |
| load_date | TIMESTAMP | | Date and time of update |

**Example (5 rows)**

| patient_ref | episode_ref | ou_loc_ref | ou_med_ref | catalog | code | descr | text | place_ref | place_descr | class | start_date | load_date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900061 | 800061 |  |  | 10 | 10E0XZZ | Example procedure description |  | 6 | Example place | P | 2099-01-05 03:25:00 | 2099-12-31 12:00:00 |
| 900061 | 800061 |  |  | 10 | 3E0P7VZ | Example procedure |  |  |  | S | 2099-01-06 14:41:00 | 2099-12-31 12:00:00 |
| 900061 | 800061 |  |  | 10 | 3E0R3BZ | Example procedure |  |  |  | S | 2099-01-08 02:04:00 | 2099-12-31 12:00:00 |
| 900062 | 800062 |  |  | 10 | GZ50ZZZ | Example procedure |  | 5 | Example place | P | 2099-01-11 08:46:00 | 2099-12-31 12:00:00 |
| 900063 | 800063 |  |  | 10 | GZ50ZZZ | Example procedure |  | 5 | Example place | P | 2099-01-14 19:19:00 | 2099-12-31 12:00:00 |


---

### provisions

Provisions are healthcare benefits. They are usually categorized into three levels: each level 1 class contains its own level 2 classes, and each level 2 class contains its own level 3 classes. However, this structure is not mandatory, so some provisions may not have any levels at all. In any case, each provision always has a code (`prov_ref`) that identifies it.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| ou_med_ref_order | VARCHAR(8) | FK | Medical organizational unit that requests the provision (look up the description via a helper query on `movements.ou_med_ref` / `ou_med_descr`) |
| prov_ref | VARCHAR(32) | | Code that identifies the healthcare provision |
| prov_descr | VARCHAR(255) | | Description of the provision code |
| level_1_ref | VARCHAR(16) | | Level 1 code; may end with '_inferido', indicating this level was not recorded in SAP but has been inferred from the context in SAP tables |
| level_1_descr | VARCHAR(45) | | Level 1 code description |
| level_2_ref | VARCHAR(3) | | Level 2 code |
| level_2_descr | VARCHAR(55) | | Level 2 code description |
| level_3_ref | VARCHAR(3) | | Level 3 code |
| level_3_descr | VARCHAR(50) | | Level 3 code description |
| category | INT | | Class of the provision: **2** (generic provisions), **6** (imaging diagnostic provisions) |
| start_date | TIMESTAMP | | Start date of the provision |
| end_date | TIMESTAMP | | End date of the provision |
| accession_number | VARCHAR(10) | PK | Unique identifier for each patient provision. For example, if a patient undergoes two ECGs on the same day, this will result in two separate provisions, each with its own accession number. This field links to the XNAT data repository |
| ou_med_ref_exec | VARCHAR(8) | FK | Medical organizational unit that executes the provision (look up the description via a helper query on `movements.ou_med_ref` / `ou_med_descr`) |
| start_date_plan | TIMESTAMP | | Scheduled start date of the provision |
| end_date_plan | TIMESTAMP | | Scheduled end date of the provision |

**Example (5 rows)**

| patient_ref | episode_ref | ou_med_ref_order | prov_ref | prov_descr | level_1_ref | level_1_descr | level_2_ref | level_2_descr | level_3_ref | level_3_descr | category | start_date | end_date | accession_number | ou_med_ref_exec | start_date_plan | end_date_plan |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900001 | 800001 | ONC | 102FNP | Example provision | VIS | visita | 171 | visita sucesiva | 176 | visita enfermeria | 2 | 2099-01-03 12:33:59 | 2099-01-03 12:33:59 | ACC001 | ONCAC | NaT | NaT |
| 900001 | 800002 | ONC | 103 | Example provision | VIS | visita | 160 | primera visita | 159 | visita medica | 2 | 2099-01-04 09:45:00 | 2099-01-04 09:45:00 | ACC002 | NRCCE | 2099-01-04 09:45:00 | 2099-01-04 09:45:00 |
| 900001 | 800002 | NRC | 9618A | Example provision | DIM | diagnostico imagen | 039 | escaner | 154 | tomografia computarizada | 6 | 2099-01-05 21:17:00 | 2099-01-05 21:17:00 | ACC003 | SCA | 2099-01-05 21:17:00 | 2099-01-05 21:17:00 |
| 900001 | 800002 | NRC | VALSNC_M | Example provision | VIS | visita | 171 | visita sucesiva | 159 | visita medica | 2 | 2099-01-06 08:45:02 | 2099-01-06 08:45:02 | ACC004 | NRCCE | NaT | NaT |
| 900001 | 800002 | NRC | 102 | Example provision | VIS | visita | 171 | visita sucesiva | 159 | visita medica | 2 | 2099-01-07 10:15:00 | 2099-01-07 10:15:00 | ACC005 | NRCCE | 2099-01-07 10:15:00 | 2099-01-07 10:15:00 |


---

### dynamic_forms

Dynamic forms collect clinical data in a structured manner. All of this data is recorded in the `dynamic_forms` table, where each dynamic form and its characteristics appear as many times as the form was saved in SAP. This is reflected in the `form_date` variable, which stores the date or dates when the form was saved.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| ou_loc_ref | VARCHAR(8) | FK | Physical hospitalization unit reference |
| ou_med_ref | VARCHAR(8) | FK | Medical organizational unit reference |
| status | VARCHAR(3) | | Record status: **CO** (completed), **EC** (in process) |
| class_ref | VARCHAR(3) | | Assessment class: **CC** (structured clinical course forms), **EF** (physical examination forms), **ES** (scale forms), **RG** (record or report forms), **RE** (special record forms), **VA** (assessment forms), **TS** (social work forms) |
| class_descr | VARCHAR | | Class description |
| form_ref | VARCHAR(8) | | Form name identifier |
| form_descr | VARCHAR | | Form description |
| form_date | TIMESTAMP | | Date when the form was saved |
| tab_ref | VARCHAR(10) | | Form tab (group) identifier |
| tab_descr | VARCHAR | | Tab description |
| section_ref | VARCHAR(10) | | Form section (parameter) identifier |
| section_descr | VARCHAR | | Section description |
| question_ref | VARCHAR(8) | | Form question (characteristic) identifier |
| question_descr | VARCHAR | | Question/characteristic description |
| class_ref | VARCHAR(3) | | Assessment class: **CC** (structured clinical course forms), **EF** (physical examination forms), **ES** (scale forms), **RG** (record or report forms), **RE** (special record forms), **VA** (assessment forms), **TS** (social work forms) |
| class_descr | VARCHAR | | Class description |
| value_num | FLOAT | | Numeric value inserted |
| value_text | VARCHAR(255) | | Text value inserted (may contain code+description, e.g. "20-Otro hospital-") |
| value_date | TIMESTAMP | | Datetime value inserted |
| value_descr | VARCHAR | | Description of the selected value (human-readable label) |
| load_date | TIMESTAMP | | Date of update |

**Dynamic forms structure:**

The components of dynamic forms follow this hierarchy:
- **Form** (form_ref, form_descr): The main container
- **Tab** (tab_ref, tab_descr): Groups within a form
- **Section** (section_ref, section_descr): Parameters within a tab
- **Question** (question_ref, question_descr): Questions/characteristics within a section

**Example (5 rows)**

| patient_ref | episode_ref | ou_loc_ref | ou_med_ref | status | class_ref | class_descr | form_ref | form_descr | form_date | tab_ref | tab_descr | section_ref | section_descr | question_ref | question_descr | value_num | value_text | value_date | value_descr | load_date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900031 | 900032 | E037 | NMO | CO | AL | Alertas | TIPUS_IRA | Example form | 2099-01-04 14:41:47 | TIPUS_IRA | Example form | P_TIPUS_IR | preguntes Example form | TIPUS_1 | causa ingres |  | 13-Ingrés per altra causa amb IRA- |  | Ingrés per altra causa amb IRA | 2099-01-05 06:01:30 |
| 900033 | 900034 | G094 | CGD | CO | AL | Alertas | CAMP_LET | Example form | 2099-01-07 08:51:54 | CAMP_LET | aet | PREG_LET | preguntas aet | LET_TXT | let_txt |  | --X |  |  | 2099-01-08 10:07:42 |
| 900033 | 900034 | G094 | CGD | CO | AL | Alertas | CAMP_LET | Example form | 2099-01-10 08:51:54 | CAMP_LET | aet | PREG_LET | preguntas aet | LET_PRINC | let_princ |  | --X |  |  | 2099-01-11 10:07:42 |
| 900033 | 900034 | G094 | CGD | CO | AL | Alertas | CAMP_LET | Example form | 2099-01-13 08:51:54 | CAMP_LET | aet | PREG_LET | preguntas aet | LET_1 | intubacion |  | -No- |  | No | 2099-01-14 10:04:56 |
| 900033 | 900034 | G094 | CGD | CO | AL | Alertas | CAMP_LET | Example form | 2099-01-16 08:51:54 | CAMP_LET | aet | PREG_LET | preguntas aet | LET_2 | vmni |  | -No- |  | No | 2099-01-17 10:04:56 |


---

### special_records

Special records (also known as nursing records) are a specific type of dynamic form completed by nurses to collect clinical data in a structured manner. All of this data is recorded in the `special_records` table, where each special record appears as many times as it was saved in SAP. Unlike `dynamic_forms`, special records use `start_date` and `end_date` for temporal bounds instead of `form_date`.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| ou_loc_ref | VARCHAR(8) | FK | Physical hospitalization unit reference |
| ou_med_ref | VARCHAR(8) | FK | Medical organizational unit reference |
| status | VARCHAR(3) | | Record status: **CO** (completed), **EC** (in process) |
| class_ref | VARCHAR(3) | | Assessment class: **RE** (special record forms) |
| class_descr | VARCHAR | | Class description |
| form_ref | VARCHAR(8) | | Form name identifier |
| form_descr | VARCHAR | | Form description |
| tab_ref | VARCHAR(10) | | Form tab (group) identifier |
| tab_descr | VARCHAR | | Tab description |
| section_ref | VARCHAR(10) | | Form section (parameter) identifier |
| section_descr | VARCHAR | | Section description |
| question_ref | VARCHAR(8) | | Form question (characteristic) identifier |
| question_descr | VARCHAR | | Question/characteristic description |
| start_date | TIMESTAMP | | Start date of the record |
| end_date | TIMESTAMP | | End date of the record |
| value_num | DOUBLE | | Numeric value inserted |
| value_text | VARCHAR(255) | | Text value inserted |
| value_descr | VARCHAR | | Description of the selected value (human-readable label) |
| load_date | TIMESTAMP | | Date of update |

**Example (5 rows)**

| patient_ref | episode_ref | ou_loc_ref | ou_med_ref | status | class_ref | class_descr | form_ref | form_descr | tab_ref | tab_descr | section_ref | section_descr | question_ref | question_descr | start_date | end_date | value_num | value_text | value_descr | load_date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900035 | 900036 | G065 | ONC | EC | RE | Formularios de Example form | REGISTRES | Example form | ESP_FERID | Example section | NAFRES | Example section | NUM_FER_N | identificador herida | 2099-01-05 14:45:38 | 2099-01-05 13:13:45 |  | 010 |  1 | 2099-01-05 10:07:34 |
| 900035 | 900036 | G065 | ONC | EC | RE | Formularios de Example form | REGISTRES | Example form | ESP_FERID | Example section | NAFRES | Example section | DATA_INSER | fecha de inicio | 2099-01-08 14:45:38 | 2099-01-08 13:13:45 |  |  | 06/04/2024 | 2099-01-08 10:15:45 |
| 900035 | 900036 | G065 | ONC | EC | RE | Formularios de Example form | REGISTRES | Example form | ESP_FERID | Example section | NAFRES | Example section | DATA_VAL | fecha de valoracion | 2099-01-11 14:45:38 | 2099-01-11 13:13:45 |  |  | 10/04/2024 | 2099-01-11 10:15:45 |
| 900035 | 900036 | G065 | ONC | EC | RE | Formularios de Example form | REGISTRES | Example form | ESP_FERID | Example section | NAFRES | Example section | LOC_GEN | localizacion general | 2099-01-14 14:45:38 | 2099-01-14 13:13:45 |  | 70 | Example location | 2099-01-14 10:07:34 |
| 900035 | 900036 | G065 | ONC | EC | RE | Formularios de Example form | REGISTRES | Example form | ESP_FERID | Example section | NAFRES | Example section | LOC_ESP_ZS | localizacion Example location | 2099-01-17 14:45:38 | 2099-01-17 13:13:45 |  | 440 | Example location | 2099-01-17 10:07:34 |


---

### tags

Tags are labels that some clinicians use to identify groups of patients. The exact meaning of each tag and its maintenance depends on the tag administrator.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| tag_ref | INT | FK | Reference identifying the tag |
| tag_group | VARCHAR | | Tag group |
| tag_subgroup | VARCHAR | | Tag subgroup |
| tag_descr | VARCHAR | | Description of the tag reference |
| inactive_atr | INT | | Inactivity: **0** (off), **1** (on) |
| start_date | TIMESTAMP | | Start date and time of the tag |
| end_date | TIMESTAMP | | End date and time of the tag |
| load_date | TIMESTAMP | | Update date and time |

**Example (5 rows)**

| patient_ref | episode_ref | tag_ref | tag_group | tag_subgroup | tag_descr | inactive_atr | start_date | end_date | load_date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900037 | 900038 | 1 | UGO | Example tag | Example tag | 0 | 2099-01-03 12:59:27 |  | 2099-01-03 14:01:08 |
| 900039 | 900040 | 1 | UGO | Example tag | Example tag | 0 | 2099-01-04 04:49:19 |  | 2099-01-04 11:05:43 |
| 900041 | 900042 | 1 | UGO | Example tag | Example tag | 0 | 2099-01-05 13:40:46 |  | 2099-01-05 10:09:05 |
| 900043 | 900044 | 1 | UGO | Example tag | Example tag | 0 | 2099-01-06 16:49:58 |  | 2099-01-06 11:17:20 |
| 900045 | 900046 | 1 | UGO | Example tag | Example tag | 0 | 2099-01-07 16:50:26 |  | 2099-01-07 10:09:05 |


---

### surgery

Contains general information about the surgical procedures.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| mov_ref | INT | FK | Reference that joins the surgery with its movement |
| ou_med_ref | VARCHAR | FK | Medical organizational unit reference |
| ou_loc_ref | VARCHAR | FK | Physical hospitalization unit reference |
| operating_room | VARCHAR | | Assigned operating room |
| start_date | TIMESTAMP | | When the surgery starts |
| end_date | TIMESTAMP | | When the surgery ends |
| surgery_ref | INT | FK | Number that identifies a surgery; links to other Surgery tables |
| surgery_code | VARCHAR | | Standard code for the surgery. Local code named Q codes (e.g., Q01972 for "injeccio intravitria") |
| surgery_code_descr | VARCHAR | | Surgery code description |

**Example (5 rows)**

| patient_ref | episode_ref | mov_ref | ou_med_ref | ou_loc_ref | operating_room | start_date | end_date | surgery_ref | surgery_code | surgery_code_descr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900047 | 100008 | 0 |  |  |  | NaT |  | 900049 | Q00726 | Example procedure |
| 900047 | 100008 | 0 |  |  |  | NaT |  | 900049 | Q00726 | Example procedure |
| 900047 | 100008 | 0 |  |  |  | NaT |  | 900049 | Q00726 | Example procedure |
| 900050 | 100001 | 4 |  |  |  | NaT |  | 900052 | Q01314 | Example procedure |
| 900053 | 100004 | 3 | CIR | BQUIR | QUI2 | 2099-01-07 12:28:00 |  | 900055 | Q00641 | Example procedure |


---

### surgery_team

Contains information about surgical tasks performed during surgical procedures.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| surgery_ref | INT | FK | Number that identifies a surgery; links to other Surgery tables |
| task_ref | VARCHAR | | Code that identifies the surgical task |
| task_descr | VARCHAR | | Description of the surgical task |
| employee | VARCHAR | | Employee who performed the task |

**Example (5 rows)**

| patient_ref | episode_ref | surgery_ref | task_ref | task_descr | employee |
| --- | --- | --- | --- | --- | --- |
| 900064 | 800064 | 700064 | CI | Example role | 900065 |
| 900064 | 800064 | 700064 | EC | Example role | 900066 |
| 900064 | 800064 | 700064 | CI | Example role | 900067 |
| 900064 | 800064 | 700064 | TCDI | Example role | 900068 |
| 900069 | 800069 | 700069 | CI | Example role | 900070 |


---

### surgery_timestamps

Stores the timestamps of surgical events for each surgical procedure.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| event_label | VARCHAR | | Surgical event code |
| event_descr | VARCHAR | | Description of the surgical event |
| event_timestamp | TIMESTAMP | | Timestamp indicating when the surgical event happened |
| surgery_ref | INT | FK | Number that identifies a surgery; links to other Surgery tables |

**Example (5 rows)**

| patient_ref | episode_ref | event_label | event_descr | event_timestamp | surgery_ref |
| --- | --- | --- | --- | --- | --- |
| 900064 | 800064 | ENTRADAQ | Example event | 2099-01-03 13:10:00 | 700064 |
| 900064 | 800064 | SUTURA | Example event | 2099-01-04 13:50:00 | 700064 |
| 900069 | 800069 | ENTRADAQ | Example event | 2099-01-05 10:07:00 | 700069 |
| 900069 | 800069 | SORTIDAQ | Example event | 2099-01-06 10:25:00 | 700069 |
| 900069 | 800069 | SUTURA | Example event | 2099-01-07 10:20:00 | 700069 |


---

### surgery_waiting_list

Contains the waiting list information for requested surgical procedures.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| surgeon_code | INT | | Code identifying the surgeon |
| waiting_list | VARCHAR | | Name of the waiting list |
| planned_date | TIMESTAMP | | Scheduled date and time of the surgical intervention |
| proc_ref | VARCHAR | FK | Procedure code |
| registration_date | TIMESTAMP | | Date and time when the patient was registered on the waiting list |
| requesting_physician | INT | | Physician who requested the surgery |
| priority | INT | | Priority assigned to the patient in the waiting list |

**Example (5 rows)**

| patient_ref | episode_ref | surgeon_code | waiting_list | planned_date | proc_ref | registration_date | requesting_physician | priority |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900063 | 100004 | 900065 | Q041 | 2099-01-03 08:00:00 |  | 2099-01-03 00:00:00 | 900066 | 9 |
| 900067 | 100008 | 900065 | Q041 | 2099-01-04 08:00:00 |  | 2099-01-04 00:00:00 | 900069 | 9 |
| 900070 | 100001 | 900072 | Q041 | 2099-01-05 08:00:00 |  | 2099-01-05 00:00:00 | 900073 | 9 |
| 900074 | 100005 | 900076 | Q051 | 2099-01-06 09:00:00 |  | 2099-01-06 00:00:00 | 900077 | 9 |
| 900078 | 100009 | 900072 | Q041 | 2099-01-07 15:00:00 |  | 2099-01-07 00:00:00 | 900073 | 9 |


---

### pathology_sample

Contains all Pathology samples and their descriptions for each case.

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| case_ref | VARCHAR | FK | Case reference |
| case_date | TIMESTAMP | | Date of the case |
| sample_ref | VARCHAR | FK | Sample reference (a case holds one or more samples) |
| sample_descr | VARCHAR | | Sample description |
| validated_by | INT | | Employee who validated the sample |

**Example (5 rows)**

| patient_ref | episode_ref | case_ref | case_date | sample_ref | sample_descr | validated_by |
| --- | --- | --- | --- | --- | --- | --- |
| 900080 | 100001 | Z17-900082 | 2099-01-03 09:01:51 | Z17-900082-COMPL1 |  | 900083 |
| 900084 | 100005 | C17-900086 | 2099-01-04 15:47:18 | C17-900086-COMPL1 |  | 900083 |
| 900084 | 100005 | C17-900086 | 2099-01-05 15:47:18 | C17-900086-COMPL2 |  | 900087 |
| 900080 | 100001 | B17-900088 | 2099-01-06 11:48:36 | B17-900088-A |  | 900089 |
| 900080 | 100001 | B17-900088 | 2099-01-07 11:48:36 | B17-900088-COMPL1 |  | 900083 |


---

### pathology_diagnostic

Contains all Pathology diagnoses associated with each case. **Especial care:  Every entity is represented in 2 registries diag_type L means location (i.e. colon)  and  diag_type M means histologic sample.(i.e. carcinoma) **

| Attribute | Data type | Key | Definition |
|-----------|-----------|-----|------------|
| patient_ref | INT | FK | Pseudonymized number that identifies a patient |
| episode_ref | INT | FK | Pseudonymized number that identifies an episode |
| case_ref | VARCHAR | FK | Case reference |
| case_date | TIMESTAMP | | Date of the case |
| sample_ref | VARCHAR | FK | Sample reference (a case holds one or more samples) |
| diag_type | VARCHAR | | Type of diagnosis: "L" Location or "M" histologic sample |
| diag_code | VARCHAR | | Diagnosis code |
| diag_date | TIMESTAMP | | Diagnosis date |
| diag_descr | VARCHAR | | Diagnosis description |
| validated_by | INT | | Employee who validated the sample |

**Example (5 rows)**

| patient_ref | episode_ref | case_ref | case_date | sample_ref | diag_type | diag_code | diag_date | diag_descr | validated_by |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 900080 | 100001 | Z17-900082 | 2099-01-03 09:01:51 | Z17-900082-B | L | 900090 | 2099-01-03 11:40:59 | colon | 900091 |
| 900080 | 100001 | Z17-900082 | 2099-01-04 09:01:51 | Z17-900082-B | M | 900092 | 2099-01-04 11:40:59 | congestión | 900091 |
| 900084 | 100005 | C17-900086 | 2099-01-05 15:47:18 | C17-900086-B | L | 900090 | 2099-01-05 16:16:09 | fascia | 7996 |
| 900084 | 100005 | C17-900086 | 2099-01-06 15:47:18 | C17-900086-B | M | 900092 | 2099-01-06 16:16:09 | congestión | 7996 |
| 900080 | 100001 | B17-900088 | 2099-01-07 11:48:36 | B17-900088-A | L | 900090 | 2099-01-07 12:09:28 | médula ósea | 900093 |


---

## Code-to-description lookups

To resolve a code (`*_ref`) to its description — or to find the code that matches a description in natural language — query the relevant fact table directly. Most fact tables already carry both columns side by side, so a `SELECT DISTINCT ref, descr` plus a `LIKE '%text%'` (or `regexp_like`) on the description is enough.

| Looking for…                               | Helper query (run against the fact table)                                                                            |
|--------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| Lab parameter code (`lab_sap_ref`)         | `SELECT DISTINCT lab_sap_ref, lab_descr FROM datascope_gestor_prod.labs WHERE lab_descr LIKE '%urea%';`              |
| Clinical record code (`rc_sap_ref`)        | `SELECT DISTINCT rc_sap_ref, rc_descr FROM datascope_gestor_prod.rc WHERE rc_descr LIKE '%presi%';`                  |
| Medical org unit (`ou_med_ref`)            | `SELECT DISTINCT ou_med_ref, ou_med_descr FROM datascope_gestor_prod.movements WHERE ou_med_descr LIKE '%cardiolog%';` |
| Physical unit (`ou_loc_ref`)               | `SELECT DISTINCT ou_loc_ref, ou_loc_descr FROM datascope_gestor_prod.movements WHERE ou_loc_descr LIKE '%uci%';`     |
| Diagnosis code (ICD-9 / ICD-10)            | `SELECT DISTINCT code, diag_descr FROM datascope_gestor_prod.diagnostics WHERE diag_descr LIKE '%diabet%';`          |
| Procedure code (ICD-9 / ICD-10)            | `SELECT DISTINCT code, descr FROM datascope_gestor_prod.procedures WHERE descr LIKE '%trasplant%';`                  |
| Surgery Q-code (`surgery_code`)            | `SELECT DISTINCT surgery_code, surgery_code_descr FROM datascope_gestor_prod.surgery WHERE surgery_code_descr LIKE '%catarata%';` |
| Drug (`drug_ref`) / ATC (`atc_ref`)        | `SELECT DISTINCT drug_ref, drug_descr, atc_ref, atc_descr FROM datascope_gestor_prod.prescriptions WHERE drug_descr LIKE '%omeprazol%';` |
| Provision code (`prov_ref`)                | `SELECT DISTINCT prov_ref, prov_descr FROM datascope_gestor_prod.provisions WHERE prov_descr LIKE '%TC%';`           |
| Microorganism (`micro_ref`)                | `SELECT DISTINCT micro_ref, micro_descr FROM datascope_gestor_prod.micro WHERE micro_descr LIKE '%coli%';`           |
| Antibiotic (`antibiotic_ref`)              | `SELECT DISTINCT antibiotic_ref, antibiotic_descr FROM datascope_gestor_prod.antibiograms WHERE antibiotic_descr LIKE '%vancomicin%';` |

**Tips when generating helper queries**:
- Always search the description in **both Catalan and Spanish** (e.g. `LIKE '%fetge%' OR LIKE '%hígado%'`) — DataNex descriptions are mixed.
- Prefer `LIKE '%...%'` for everyday lookups; use `regexp_like(col, 'pattern')` when you need anchors, alternations or case-insensitive flags.
- Once the user pastes the codes back, switch to an explicit `IN ('CODE1','CODE2', …)` filter on the `_ref` / `code` column in the main query — faster and unambiguous.

---

## Key Relationships

### Primary Identifiers
- `patient_ref`: Links most tables (primary patient identifier)
- `episode_ref`: Links to hospital episodes

### Hierarchical Relationships
- Tables follow the hierarchy: **episodes → care_levels → movements**
- `care_level_ref`: Groups consecutive care levels (ICU, WARD, etc.) if they belong to the same level

### Treatment Chain
- `treatment_ref`: Links `prescriptions`, `administrations`, and `perfusions`

### Surgery Chain
- `surgery_ref`: Links `surgery`, `surgery_team`, and `surgery_timestamps`

### Pathology Chain
- `case_ref` and `sample_ref`: Link `pathology_sample` and `pathology_diagnostic`

### Microbiology Chain
- `antibiogram_ref`: Links `micro` and `antibiograms`

---

## Common code samples (`ref:descr` format)

**Usage**: These are illustrative codes that the helper queries described in "Code-to-description lookups" return when run against the corresponding fact tables. They are **not** an exhaustive list, and they are **not** stored in any dictionary table — `dic_*` tables no longer exist. Use the samples to recognise common values; for any specific lookup, generate the appropriate helper query against the fact table.

### Diagnoses — found in `diagnostics.code` + `diagnostics.diag_descr` (sample entries)

```
M15.4:(osteo)artrosis erosiva
M15.0:(osteo)artrosis primaria generalizada
715.09:(osteo)artrosis primaria generalizada
R10.0:Abdomen agudo
Z43:Abertura artificial, no especificada
...
```

### Lab parameters — found in `labs.lab_sap_ref` + `labs.lab_descr` (sample entries)

```
LAB110:Urea
LAB1100:Tiempo de protombina segundos
LAB1101:Tiempo de tromboplastina parcial
LAB1102:Fibrinogeno
LAB1111:Grup ABO
LAB1112:Rh (D)
LAB1173:INR
LAB1300:Leucocitos recuento
LAB1301:Plaquetas recuento
...
```

### Physical hospitalization units — found in `movements.ou_loc_ref` + `movements.ou_loc_descr` (sample entries)

```
HAH:HAH SALA HOSP. DOMICILIARIA
ICU:CUIDADOS INTENSIVOS
WARD:HOSPITALIZACIÓN CONVENCIONAL
ELE1:SE NEONAT.MAT.UCI ELE1
EPT0:EPT0 CUIDADOS INTENSIVOS PLATÓ PL.0
...
```

### Medical organizational units — found in `movements.ou_med_ref` + `movements.ou_med_descr` (sample entries)

```
ANE:ANESTESIOLOGIA I REANIMACIO
CAR:CARDIOLOGIA
HMT:BANC DE SANG
BCL:BARNACLÍNIC
NEU:NEUROLOGIA
...
```

### Clinical records — found in `rc.rc_sap_ref` + `rc.rc_descr` (sample entries)

```
ABDOMEN_DIST:Distensión abdominal
APACHE_II:Valoración de gravedad del enfermo crítico
FC:Frecuencia cardíaca
TAS:Tensión arterial sistólica
TAD:Tensión arterial diastólica
TEMP:Temperatura
...
```

---

## Query Examples (Athena / Trino dialect)

### Example 1: Patients with specific diagnosis
```sql
WITH diagnosis_search AS (
    SELECT DISTINCT patient_ref, episode_ref, diag_descr
    FROM datascope_gestor_prod.diagnostics
    WHERE diag_descr LIKE '%diabetes%'
)
SELECT * FROM diagnosis_search;
```

### Example 2: Laboratory results in date range
```sql
WITH lab_results AS (
    SELECT
        patient_ref,
        episode_ref,
        lab_sap_ref,
        lab_descr,
        result_num,
        units,
        extrac_date
    FROM datascope_gestor_prod.labs
    WHERE extrac_date >= timestamp '2024-01-01 00:00:00'
      AND extrac_date <  timestamp '2025-01-01 00:00:00'
      AND lab_sap_ref = 'LAB110'  -- Urea
)
SELECT * FROM lab_results
ORDER BY patient_ref, extrac_date;
```

### Example 3: Patient demographics with episodes
```sql
WITH patient_episodes AS (
    SELECT DISTINCT
        e.patient_ref,
        e.episode_ref,
        e.episode_type_ref,
        e.start_date,
        e.end_date
    FROM datascope_gestor_prod.episodes e
),
patient_info AS (
    SELECT
        d.patient_ref,
        d.birth_date,
        d.sex,
        d.natio_descr
    FROM datascope_gestor_prod.demographics d
)
SELECT
    pe.*,
    pi.birth_date,
    pi.sex,
    pi.natio_descr
FROM patient_episodes pe
JOIN patient_info pi ON pe.patient_ref = pi.patient_ref;
```

### Example 4: Drug administrations with prescriptions
```sql
WITH prescriptions_cte AS (
    SELECT
        patient_ref,
        episode_ref,
        treatment_ref,
        drug_ref,
        drug_descr,
        atc_ref,
        dose,
        unit
    FROM datascope_gestor_prod.prescriptions
    WHERE atc_ref LIKE '%J01%'  -- Antibacterials
),
administrations_cte AS (
    SELECT
        patient_ref,
        episode_ref,
        treatment_ref,
        administration_date,
        quantity,
        quantity_unit
    FROM datascope_gestor_prod.administrations
)
SELECT
    p.*,
    a.administration_date,
    a.quantity
FROM prescriptions_cte p
JOIN administrations_cte a
    ON p.patient_ref = a.patient_ref
   AND p.treatment_ref = a.treatment_ref;
```

### Example 5: Microbiology with antibiograms
```sql
WITH micro_positive AS (
    SELECT
        patient_ref,
        episode_ref,
        extrac_date,
        micro_ref,
        micro_descr,
        antibiogram_ref
    FROM datascope_gestor_prod.micro
    WHERE positive = 'X'
),
antibiogram_results AS (
    SELECT
        patient_ref,
        antibiogram_ref,
        antibiotic_descr,
        sensitivity
    FROM datascope_gestor_prod.antibiograms
)
SELECT
    mp.*,
    ar.antibiotic_descr,
    ar.sensitivity
FROM micro_positive mp
JOIN antibiogram_results ar
    ON mp.patient_ref = ar.patient_ref
   AND mp.antibiogram_ref = ar.antibiogram_ref;
```

### Example 6: Multiple transplant types by year with pivot (ADVANCED)
```sql
SELECT
  tipo_trasplante,
  SUM(CASE WHEN anio = 2015 THEN total_trasplantes ELSE 0 END) AS "2015",
  SUM(CASE WHEN anio = 2016 THEN total_trasplantes ELSE 0 END) AS "2016",
  SUM(CASE WHEN anio = 2017 THEN total_trasplantes ELSE 0 END) AS "2017",
  SUM(CASE WHEN anio = 2018 THEN total_trasplantes ELSE 0 END) AS "2018",
  SUM(CASE WHEN anio = 2019 THEN total_trasplantes ELSE 0 END) AS "2019",
  SUM(CASE WHEN anio = 2020 THEN total_trasplantes ELSE 0 END) AS "2020",
  SUM(CASE WHEN anio = 2021 THEN total_trasplantes ELSE 0 END) AS "2021",
  SUM(CASE WHEN anio = 2022 THEN total_trasplantes ELSE 0 END) AS "2022",
  SUM(CASE WHEN anio = 2023 THEN total_trasplantes ELSE 0 END) AS "2023",
  SUM(CASE WHEN anio = 2024 THEN total_trasplantes ELSE 0 END) AS "2024"
FROM (
  SELECT
    'Trasplante cardiaco' AS tipo_trasplante,
    year(start_date) AS anio,
    COUNT(DISTINCT patient_ref) AS total_trasplantes
  FROM datascope_gestor_prod.procedures
  WHERE start_date >= timestamp '2015-01-01 00:00:00'
    AND start_date <  timestamp '2025-01-01 00:00:00'
    AND (code LIKE '37.51%' OR code LIKE '02YA%')
  GROUP BY year(start_date)

  UNION ALL

  SELECT
    'Trasplante de cornea' AS tipo_trasplante,
    year(start_date) AS anio,
    COUNT(DISTINCT patient_ref) AS total_trasplantes
  FROM datascope_gestor_prod.procedures
  WHERE start_date >= timestamp '2015-01-01 00:00:00'
    AND start_date <  timestamp '2025-01-01 00:00:00'
    AND code LIKE '11.6%'
  GROUP BY year(start_date)

  UNION ALL

  SELECT
    'Trasplante de medula osea/celulas madre' AS tipo_trasplante,
    year(start_date) AS anio,
    COUNT(DISTINCT patient_ref) AS total_trasplantes
  FROM datascope_gestor_prod.procedures
  WHERE start_date >= timestamp '2015-01-01 00:00:00'
    AND start_date <  timestamp '2025-01-01 00:00:00'
    AND code LIKE '41.0%'
  GROUP BY year(start_date)

  UNION ALL

  SELECT
    'Trasplante de pancreas' AS tipo_trasplante,
    year(start_date) AS anio,
    COUNT(DISTINCT patient_ref) AS total_trasplantes
  FROM datascope_gestor_prod.procedures
  WHERE start_date >= timestamp '2015-01-01 00:00:00'
    AND start_date <  timestamp '2025-01-01 00:00:00'
    AND (code LIKE '52.8%' OR code LIKE '0FYG%')
  GROUP BY year(start_date)

  UNION ALL

  SELECT
    'Trasplante hepatico' AS tipo_trasplante,
    year(start_date) AS anio,
    COUNT(DISTINCT patient_ref) AS total_trasplantes
  FROM datascope_gestor_prod.procedures
  WHERE start_date >= timestamp '2015-01-01 00:00:00'
    AND start_date <  timestamp '2025-01-01 00:00:00'
    AND (code LIKE '50.5%' OR code LIKE '0FY0%')
  GROUP BY year(start_date)

  UNION ALL

  SELECT
    'Trasplante renal' AS tipo_trasplante,
    year(start_date) AS anio,
    COUNT(DISTINCT patient_ref) AS total_trasplantes
  FROM datascope_gestor_prod.procedures
  WHERE start_date >= timestamp '2015-01-01 00:00:00'
    AND start_date <  timestamp '2025-01-01 00:00:00'
    AND (code LIKE '55.6%' OR code LIKE '0TY0%' OR code LIKE '0TY1%')
  GROUP BY year(start_date)
) AS datos
GROUP BY tipo_trasplante
ORDER BY tipo_trasplante;
```

### Example 7: Surgical procedures with team and timestamps
```sql
WITH surgeries AS (
    SELECT
        s.patient_ref,
        s.episode_ref,
        s.surgery_ref,
        s.surgery_code,
        s.surgery_code_descr,
        s.start_date,
        s.end_date,
        s.operating_room
    FROM datascope_gestor_prod.surgery s
),
surgery_teams AS (
    SELECT
        st.surgery_ref,
        st.task_descr,
        st.employee
    FROM datascope_gestor_prod.surgery_team st
),
surgery_events AS (
    SELECT
        sts.surgery_ref,
        sts.event_descr,
        sts.event_timestamp
    FROM datascope_gestor_prod.surgery_timestamps sts
)
SELECT
    su.*,
    st.task_descr,
    se.event_descr,
    se.event_timestamp
FROM surgeries su
LEFT JOIN surgery_teams st ON su.surgery_ref = st.surgery_ref
LEFT JOIN surgery_events se ON su.surgery_ref = se.surgery_ref
ORDER BY su.patient_ref, su.start_date, se.event_timestamp;
```

### Example 8: Clinical records (`rc`) joined to episodes via temporal window

Because `rc.episode_ref` is currently NULL, we cannot join `rc` to `episodes` on `episode_ref`. The idiomatic pattern is: build the episode cohort first, then attach `rc` rows by `patient_ref` + a temporal window on `result_date`.

```sql
WITH episode_cohort AS (
    SELECT
        patient_ref,
        episode_ref,
        start_date,
        end_date
    FROM datascope_gestor_prod.episodes
    WHERE episode_type_ref = 'HOSP'
      AND start_date >= timestamp '2024-01-01 00:00:00'
      AND start_date <  timestamp '2025-01-01 00:00:00'
),
rc_during_episode AS (
    SELECT
        c.patient_ref,
        c.episode_ref,
        r.rc_sap_ref,
        r.rc_descr,
        r.result_num,
        r.units,
        r.result_date
    FROM episode_cohort c
    JOIN datascope_gestor_prod.rc r
      ON  r.patient_ref = c.patient_ref
      -- Temporal window: rc.result_date must fall inside the episode
      AND r.result_date >= c.start_date
      AND r.result_date <  COALESCE(c.end_date, current_timestamp)
    WHERE r.rc_sap_ref IN ('TAS', 'TAD', 'FC', 'TEMP')  -- example vital signs
)
SELECT *
FROM rc_during_episode
ORDER BY patient_ref, episode_ref, result_date;
```

Key points:
- `rc` is joined on `patient_ref`, never on `episode_ref`.
- The temporal predicate anchors each `rc` row to the right episode.
- `COALESCE(c.end_date, current_timestamp)` handles still-open episodes.


### Example 9: Hospitalisation ward stays with predominant unit assignment (ADVANCED)
```sql
-- =============================================================================
-- Hospitalisation ward stays with predominant unit assignment.
-- Units: E073, I073 | Year: 2024
-- Schema (Athena): all tables fully-qualified as datascope_gestor_prod.<table>
--   (movements, demographics, exitus, prescriptions)
-- Structure: one CTE per conceptual stage, named for readability.
--   1. all_related_moves  -> movements touching the target units
--   2. flagged_starts     -> flag the first movement of each new stay
--   3. grouped_stays      -> assign a stay_id to each contiguous stay
--   4. time_per_unit      -> minutes spent in each unit within a stay
--   5. predominant_unit   -> the unit where the patient spent the most time
--   6. cohort             -> stay-level aggregation + filters
--   Final SELECT          -> enrich with demographics and exitus info
-- Athena dialect notes:
--   TIMESTAMPDIFF(MINUTE, a, b)  ->  date_diff('minute', a, b)
--   NOW()                        ->  current_timestamp
--   YEAR(x)                      ->  year(x)
-- =============================================================================
WITH all_related_moves AS (
    SELECT
        patient_ref,
        episode_ref,
        ou_loc_ref,
        start_date,
        end_date,
        COALESCE(end_date, current_timestamp) AS effective_end_date
    FROM datascope_gestor_prod.movements
    WHERE ou_loc_ref IN ('E073','I073')
      AND start_date <= timestamp '2024-12-31 23:59:59'
      AND COALESCE(end_date, current_timestamp) >= timestamp '2024-01-01 00:00:00'
      AND place_ref IS NOT NULL
      AND COALESCE(end_date, current_timestamp) > start_date
),
flagged_starts AS (
    SELECT
        m.*,
        CASE
            WHEN ABS(date_diff('minute',
                LAG(effective_end_date) OVER (
                    PARTITION BY episode_ref ORDER BY start_date
                ),
                start_date
            )) <= 5
            THEN 0
            ELSE 1
        END AS is_new_stay
    FROM all_related_moves m
),
grouped_stays AS (
    SELECT
        f.*,
        SUM(is_new_stay) OVER (
            PARTITION BY episode_ref ORDER BY start_date
        ) AS stay_id
    FROM flagged_starts f
),
time_per_unit AS (
    SELECT
        patient_ref,
        episode_ref,
        stay_id,
        ou_loc_ref,
        SUM(date_diff('minute', start_date, effective_end_date)) AS minutes_in_unit
    FROM grouped_stays
    GROUP BY patient_ref, episode_ref, stay_id, ou_loc_ref
),
predominant_unit AS (
    SELECT
        patient_ref,
        episode_ref,
        stay_id,
        ou_loc_ref AS assigned_unit,
        minutes_in_unit AS max_minutes
    FROM (
        SELECT
            t.patient_ref,
            t.episode_ref,
            t.stay_id,
            t.ou_loc_ref,
            t.minutes_in_unit,
            ROW_NUMBER() OVER (
                PARTITION BY t.patient_ref, t.episode_ref, t.stay_id
                ORDER BY t.minutes_in_unit DESC, MIN(g.start_date) ASC
            ) AS rn
        FROM time_per_unit t
        INNER JOIN grouped_stays g
            ON  t.patient_ref = g.patient_ref
            AND t.episode_ref = g.episode_ref
            AND t.stay_id     = g.stay_id
            AND t.ou_loc_ref  = g.ou_loc_ref
        GROUP BY t.patient_ref, t.episode_ref, t.stay_id,
                 t.ou_loc_ref, t.minutes_in_unit
    ) ranked
    WHERE rn = 1
),
cohort AS (
    SELECT
        g.patient_ref,
        g.episode_ref,
        g.stay_id,
        p.assigned_unit AS ou_loc_ref,
        MIN(g.start_date) AS admission_date,
        MAX(g.end_date)   AS discharge_date,
        MAX(g.effective_end_date) AS effective_discharge_date,
        date_diff('hour',   MIN(g.start_date), MAX(g.effective_end_date)) AS hours_stay,
        date_diff('day',    MIN(g.start_date), MAX(g.effective_end_date)) AS days_stay,
        date_diff('minute', MIN(g.start_date), MAX(g.effective_end_date)) AS minutes_stay,
        CASE WHEN MAX(g.end_date) IS NULL THEN 'Yes' ELSE 'No' END AS still_admitted,
        COUNT(*) AS num_movements,
        COUNT(DISTINCT g.ou_loc_ref) AS num_units_visited,
        SUM(CASE WHEN g.ou_loc_ref = 'E073'
            THEN date_diff('minute', g.start_date, COALESCE(g.end_date, current_timestamp))
            ELSE 0 END) AS minutes_E073,
        SUM(CASE WHEN g.ou_loc_ref = 'I073'
            THEN date_diff('minute', g.start_date, COALESCE(g.end_date, current_timestamp))
            ELSE 0 END) AS minutes_I073
    FROM grouped_stays g
    INNER JOIN predominant_unit p
        ON  g.patient_ref = p.patient_ref
        AND g.episode_ref = p.episode_ref
        AND g.stay_id     = p.stay_id
    GROUP BY g.patient_ref, g.episode_ref, g.stay_id, p.assigned_unit
    HAVING year(MIN(g.start_date)) = 2024
)
SELECT DISTINCT
    c.patient_ref,
    c.episode_ref,
    c.stay_id,
    c.ou_loc_ref,
    c.admission_date,
    c.discharge_date,
    c.effective_discharge_date,
    c.hours_stay,
    c.days_stay,
    c.minutes_stay,
    c.still_admitted,
    c.num_movements,
    c.num_units_visited,
    c.minutes_E073,
    c.minutes_I073,
    CASE WHEN c.num_units_visited > 1 THEN 'Yes' ELSE 'No' END AS had_transfer,
    year(c.admission_date) AS year_admission,
    date_diff('year', d.birth_date, c.admission_date) AS age_at_admission,
    CASE
        WHEN d.sex = 1 THEN 'Male'
        WHEN d.sex = 2 THEN 'Female'
        WHEN d.sex = 3 THEN 'Other'
        ELSE 'Not reported'
    END AS sex,
    CASE
        WHEN ex.exitus_date IS NOT NULL
             AND ex.exitus_date BETWEEN CAST(c.admission_date AS date)
                 AND CAST(c.effective_discharge_date AS date)
        THEN 'Yes'
        ELSE 'No'
    END AS exitus_during_stay,
    ex.exitus_date
FROM cohort c
LEFT JOIN datascope_gestor_prod.demographics d
    ON c.patient_ref = d.patient_ref
LEFT JOIN datascope_gestor_prod.exitus ex
    ON c.patient_ref = ex.patient_ref
INNER JOIN datascope_gestor_prod.prescriptions p
    ON  c.patient_ref = p.patient_ref
    AND c.episode_ref = p.episode_ref
    AND p.start_drug_date BETWEEN c.admission_date
        AND c.effective_discharge_date
ORDER BY c.admission_date;
```


---

# DataNex free-text clinical notes — the `clinical_reports` table

Everything above describes the **structured** DataNex tables. In addition to all of them there is one more table, **`clinical_reports`**, which does not store structured data but **free clinical text** (clinical notes) organized into nested sections.

It lives in the same database and follows every global rule already stated in this document — same **Athena / Trino / Presto** dialect, same **mandatory `datascope_gestor_prod.` schema qualification**, and the same read-only and privacy defaults. Those rules are not restated here; what follows documents only what is **specific** to this table.

What is specific to `clinical_reports`:

- Reference it as `datascope_gestor_prod.clinical_reports` (alias `cr`). Do not invent columns, section codes or `type` codes.
- The clinical text lives in a nested `sections` array; to read any text you must `CROSS JOIN UNNEST(cr.sections)`. Because that multiplies rows, count unique entities with `COUNT(DISTINCT ...)`.
- The `type` column is the document type (discharge, admission, results, surgical…). Do not confuse it with `sec.section_id`, which is a section *inside* the document.
- Searches run over free text in `sec.section_text` (written in Catalan/Spanish, with abbreviations and typos), so prefer `regexp_like(lower(coalesce(sec.section_text, '')), ...)` with variants.
- By default do not return `identifiable_data`. If a requested variable does not exist in the table, propose an approximate text search or note that another table would be needed.

Minimal query template:

```sql
SELECT ...
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE ...
```

## 1. Main schema

### Table

```sql
datascope_gestor_prod.clinical_reports
```

### Known columns

| Column | Description | Common use |
|---|---|---|
| `id` | Clinical report identifier | Count reports, return results, deduplicate |
| `version` | Report version | If there are several versions, pick the most recent |
| `creation_date` | Report creation date | Temporal filters, aggregations per day/month/year |
| `type` | Documentary type code of the report | Filter or aggregate by report/document type; see the `type` dictionary |
| `patient_ref` | Pseudonymized patient identifier | Count patients or return clinical identifier |
| `episode_ref` | Pseudonymized episode identifier | Count episodes |
| `identifiable_data` | Identifying patient data | Avoid by default |
| `demographic_data` | Demographic data | Age, sex, country, postal code if available |
| `sections` | Array of textual sections of the report | Main field to query clinical text |

### Recommended functional key

- A report: `id`
- A patient: `patient_ref`
- A care episode: `episode_ref`
- A textual section: an element of `sections`

### Example of an updated JSON record

The input format now includes the `type` field at the top level of the report, between the report metadata and the patient data. The following example is schematic and anonymized; it does not reproduce real identifying data.

```json
[
  {
    "id": "10,000,000,000,000,000",
    "version": "0",
    "creation_date": "2025-03-11",
    "type": "IA_ALTA",
    "patient_ref": "0000000",
    "episode_ref": "0000000000",
    "identifiable_data": {
      "first_name": "...",
      "last_name1": "...",
      "last_name2": "...",
      "cip": "...",
      "phone": "...",
      "address": "...",
      "email": null,
      "dni": "...",
      "ssn": null,
      "prosthesis_code": null
    },
    "demographic_data": {
      "birth_date": "dd.MM.yyyy",
      "postal_code": "08000",
      "sex": "1",
      "nation": "ES"
    },
    "sections": [
      {
        "section_id": "ANTEC",
        "section_index": 0,
        "section_text": "Clinical text of the section..."
      }
    ]
  }
]
```

### The `type` field: documentary type of the report

`type` is a top-level structured field of `clinical_reports` and identifies the type of document or report. In SQL queries it must be referenced as `cr.type`.

It must not be confused with `sec.section_id`:

- `cr.type` describes the type of the whole document, for example `IA_ALTA`, `IA_ADMISN`, `IQ` or `IR_RX`.
- `sec.section_id` describes an internal section of the document, for example `ANTEC`, `MOTIV_CON2`, `EXPL_CLIN` or `EVOL`.

Usage examples:

```sql
WHERE cr.type = 'IA_ALTA'
```

```sql
WHERE cr.type IN ('IA_ALTA', 'IA_ALTA_EN', 'IA_ALTA_EC', 'IA_ALTA_TE')
```

If the user asks for "report type", "document class", "discharge reports", "admission reports", "results reports", "surgical reports" or similar phrasings, try to map it to the `type` code using the dictionary below. If the phrasing is ambiguous, return a conservative query with the most directly related codes or explain the assumption.

#### `type` dictionary

| `type` | Description |
|---|---|
| `IA_UDT` | Chest pain unit discharge report |
| `IA_PRETPH` | Pre-liver-transplant report |
| `IR_MICROB` | Microbiology results report |
| `IQ_SEGQUIR` | Surgical information |
| `IQ` | Surgical information. Surgical report written by the surgeon |
| `IR_ECO_GI2` | Gynecological ultrasound results report |
| `IR_PSI_CLI` | Clinical psychology results report |
| `IT_AFERSS` | Plasma apheresis report |
| `IA_IPA` | Advanced practice nurse (APN) report |
| `IR` | Generic results report |
| `RD_PAC` | Description not provided |
| `IA_ALTA_EN` | Nursing discharge report |
| `IR_ANP` | Pathological anatomy results report |
| `IA_VAL_INI` | Initial assessment report / admission report |
| `IA_EVOL` | Progress report |
| `IQ_PREANS` | Pre-anesthesia report |
| `IR_IMAGEN` | Unreported radiology report. Not valid |
| `IQ_ENF_CIR` | Surgical nurse report |
| `IR_URODIN` | Urodynamics results report |
| `IA_ALTA_EC` | Short-stay discharge report / short admission |
| `N2_LABOR` | Description not provided |
| `IR_MOTIL_D` | Digestive motility report |
| `IR_ENDS_DI` | Digestive endoscopy results report |
| `RD_MED` | Description not provided |
| `THE_TRASP` | Transplant assessment report |
| `IR_POTN_EV` | Description not provided |
| `IA_CSMA` | Description not provided |
| `IQ_ENF_ANE` | Anesthesia nursing report |
| `IR_IMAGE` | Imaging report |
| `IA_ACTA` | Description not provided |
| `IQ_ANEST` | Anesthesia / anesthesiologist report |
| `IQ_PERFUS` | Perfusionists report / extracorporeal circulation |
| `IT_DOLR` | Pain consultation |
| `IR_EMG` | Electromyography results report |
| `IA_UFISS_P` | Social services discharge report |
| `IR_ECO_FET` | Fetal ultrasound results report |
| `IA_ALTA_TE` | Therapy discharge report |
| `IR_EEG` | Electroencephalogram results report |
| `IA_ADMISN` | Admission report / inpatient admission report |
| `IA_SOM` | Description not provided |
| `IA_IPA_HC3` | Description not provided |
| `IR_TECRAD` | Radiology technician results report |
| `IT_AFERRPH` | Description not provided |
| `TF1_PROT` | Description not provided |
| `IR_HIST` | Hysteroscopy results report |
| `IA_UFISS` | Social workers discharge report |
| `IR_CISTOS` | Cystoscopy results report |
| `IR_ECO_GIN` | Gynecological ultrasound results report |
| `IA_INTR` | Inter-consultations report |
| `IR_ECO_ATR` | Not valid |
| `IA_FAT_CRO` | Chronic fatigue report |
| `IR_DOPPLR` | Doppler report |
| `IQ_VPAS` | Pre-anesthesia nursing visit |
| `IR_END_RES` | Respiratory endoscopy results report |
| `IR_PR_ESFR` | Description not provided |
| `IR_UROD_UR` | Urodynamics results report |
| `IQ_ARTRO` | Arthroscopy surgical report |
| `NOTAS_FARM` | Pharmacy notes |
| `IR_ANDROLG` | Andrology results report |
| `IR_PSI_TEC` | Psychiatry results report / electroconvulsive therapy |
| `IA_TELECN` | Ophthalmology report |
| `IR_ECO_OBS` | Obstetric ultrasound results report |
| `IR_HOLTR` | Holter results report |
| `IR_6MWT` | 6-minute walking test results report |
| `IR_ELA_HEP` | Hepatic elastography results report |
| `IR_RX` | Radiology report |
| `DT_SOL_ANP` | Not valid |
| `IR_ALERG` | Allergology results report |
| `IQ_ANEST_P` | Anesthesia report |
| `IR_FOTOT` | Phototherapy results report |
| `IR_HEM_HEP` | Hepatic hemodynamics report |
| `IA_A_E_NNT` | Description not provided |
| `IA_ALTA` | Discharge report |
| `IQ_INCANES` | Description not provided |
| `IA_TRA_CAT` | Description not provided |
| `IA_COMPL` | Description not provided |
| `IA_PART` | Delivery / obstetrics report |
| `NOTA_CLIN` | Clinical course report |
| `IA_TRASL` | Transfer report |
| `IA_SOCL` | Description not provided |
| `IR_CRI_CCR` | Colorectal cancer screening results report |

#### Indicative `type` groupings

Use these groupings only when the user does not specify an exact code and the documentary intent is clear.

General care discharge:

```sql
cr.type IN ('IA_ALTA', 'IA_ALTA_EN', 'IA_ALTA_EC', 'IA_ALTA_TE', 'IA_UDT')
```

Admission, hospital admission or initial assessment:

```sql
cr.type IN ('IA_ADMISN', 'IA_VAL_INI')
```

Results and complementary tests:

```sql
cr.type IN (
  'IR', 'IR_MICROB', 'IR_ANP', 'IR_IMAGE', 'IR_IMAGEN', 'IR_RX', 'IR_ECO_GI2',
  'IR_ECO_GIN', 'IR_ECO_FET', 'IR_ECO_OBS', 'IR_DOPPLR', 'IR_EMG', 'IR_EEG',
  'IR_HOLTR', 'IR_CISTOS', 'IR_URODIN', 'IR_UROD_UR', 'IR_ENDS_DI', 'IR_END_RES',
  'IR_MOTIL_D', 'IR_HIST', 'IR_ANDROLG', 'IR_ALERG', 'IR_FOTOT', 'IR_HEM_HEP',
  'IR_ELA_HEP', 'IR_6MWT', 'IR_CRI_CCR', 'IR_TECRAD', 'IR_PSI_CLI', 'IR_PSI_TEC'
)
```

Surgical reports, anesthesia and surgical circuit:

```sql
cr.type IN (
  'IQ', 'IQ_SEGQUIR', 'IQ_PREANS', 'IQ_ENF_CIR', 'IQ_ENF_ANE', 'IQ_ANEST',
  'IQ_ANEST_P', 'IQ_PERFUS', 'IQ_VPAS', 'IQ_ARTRO'
)
```

Consultations and specific assessments:

```sql
cr.type IN ('IA_INTR', 'IT_DOLR', 'IT_AFERSS', 'THE_TRASP', 'IA_PRETPH', 'IA_IPA')
```

---

## 2. Nested structure of `sections`

The `sections` column contains an array of sections. Each section has, at a minimum:

| Field | Meaning |
|---|---|
| `section_id` | Section code |
| `section_text` | Free clinical text of the section |

The correct way to query it in Athena is:

```sql
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
```

And then access the fields like this:

```sql
sec.section_id
sec.section_text
```

Minimal example:

```sql
SELECT
  cr.id AS report_id,
  cr.creation_date,
  cr.type AS report_type,
  cr.patient_ref,
  cr.episode_ref,
  sec.section_id,
  sec.section_text
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
LIMIT 100;
```

### Important

Do not try to filter `sections.section_id` directly without `UNNEST`.

Incorrect:

```sql
WHERE sections.section_id = 'MOTIV_CONS'
```

Correct:

```sql
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE sec.section_id = 'MOTIV_CONS'
```

If you need to preserve the order of the sections within the report, use `WITH ORDINALITY`:

```sql
CROSS JOIN UNNEST(cr.sections) WITH ORDINALITY AS u(sec, section_pos)
```

---

## 3. Dictionary of `sections.section_id`

| `section_id` | Clinical meaning |
|---|---|
| `MOTIV_CONS` | Reason for consultation |
| `ZEXPFIS` | Physical examination |
| `OBSR` | Observations |
| `ZOBSR_ANE` | Observations of the anesthetic procedure report |
| `OTR_ANTPER` | Personal history |
| `DAT_NEONAT` | Neonatal data |
| `DAT_PARTO` | Delivery data |
| `PUERPERIO` | Puerperium data |
| `NOTA_CLN` | Clinical note |
| `N2LACOMM` | Laboratory/test comments or notes |
| `EXP_COMPL` | Complementary examinations |
| `CLIN` | Description of the clinical status in a request for a complementary examination |
| `GEST_ACT` | Current pregnancy |
| `IND_ALTA` | Discharge instructions |
| `ANTEC` | History (antecedents) |
| `PROC_ACTL` | Current process |
| `CONCL` | Conclusions |
| `EXPL_CLIN` | Clinical examination |
| `MOTIV_CON2` | Reason for consultation |
| `PROC_ACTL2` | Current process |
| `IN_FDRENAT` | Drainage |
| `EVOL` | Progress (evolution) |
| `RESL` | Results |
| `RECO_TEXT` | Recommendations or related free text |
| `TXT_DIAGN` | Diagnosis in plain text |
| `ORI_DIAG` | Diagnostic orientation |
| `PLAN_TER` | Therapeutic plan |
| `PLAN_TERA` | Therapeutic plan |
| `SEGUIMN` | Follow-up |

---

## 4. Useful section groupings by clinical intent

When the user does not specify a particular section, choose relevant sections based on the intent.

### Reason for consultation

```sql
sec.section_id IN ('MOTIV_CONS', 'MOTIV_CON2')
```

### Current process / current anamnesis

```sql
sec.section_id IN ('PROC_ACTL', 'PROC_ACTL2')
```

### Physical or clinical examination

```sql
sec.section_id IN ('ZEXPFIS', 'EXPL_CLIN')
```

### History (antecedents)

```sql
sec.section_id IN ('ANTEC', 'OTR_ANTPER')
```

### Diagnosis or diagnostic orientation

```sql
sec.section_id IN ('TXT_DIAGN', 'ORI_DIAG', 'CONCL')
```

If the question asks for "diagnosis" but it may appear in clinical narrative, you can also include:

```sql
sec.section_id IN ('TXT_DIAGN', 'ORI_DIAG', 'CONCL', 'PROC_ACTL', 'PROC_ACTL2', 'EVOL')
```

### Treatment, plan, instructions or follow-up

```sql
sec.section_id IN ('PLAN_TER', 'PLAN_TERA', 'IND_ALTA', 'SEGUIMN', 'EVOL', 'RECO_TEXT')
```

### Complementary tests, results or laboratory

```sql
sec.section_id IN ('EXP_COMPL', 'RESL', 'N2LACOMM', 'CLIN')
```

### Obstetrics, neonatology and puerperium

```sql
sec.section_id IN ('GEST_ACT', 'DAT_NEONAT', 'DAT_PARTO', 'PUERPERIO')
```

### Anesthesia / procedures

```sql
sec.section_id IN ('ZOBSR_ANE', 'IN_FDRENAT', 'OBSR')
```

---

## 5. Text searches in clinical notes

Reports may be written in Catalan, Spanish, clinical abbreviations, typos or imperfect encoding. For that reason, it is better to use regular expressions with variants.

Recommended pattern:

```sql
regexp_like(lower(coalesce(sec.section_text, '')), 'term1|term2|variant')
```

Example:

```sql
regexp_like(
  lower(coalesce(sec.section_text, '')),
  'endoftalmitis|endophthalmitis'
)
```

For a simple search you can also do:

```sql
lower(coalesce(sec.section_text, '')) LIKE '%hipoacusia%'
```

But `regexp_like` is preferable if you need synonyms, accents or variants:

```sql
regexp_like(
  lower(coalesce(sec.section_text, '')),
  'hipoacusia|hipoac[uú]sia|p[eé]rdua auditiva|p[eé]rdida auditiva'
)
```

### Accents and languages

Athena does not necessarily provide an `unaccent` function. Include variants with and without accents when it matters:

```sql
'dolor tor[aà]cic|dolor toracico|dolor tor[aá]cico'
```

### Negations

Do not assume a mention is positive if it may appear negated. When clinically important, try to exclude simple negations:

```sql
regexp_like(lower(coalesce(sec.section_text, '')), 'diabet')
AND NOT regexp_like(lower(coalesce(sec.section_text, '')), 'no diabet|sense diabet|sin diabet')
```

This exclusion is approximate and does not replace a clinical negation-detection model.

---

## 6. Dates

`creation_date` is the report creation date. It may appear as a date or as text in `YYYY-MM-DD` format.

Recommended filter:

```sql
CAST(cr.creation_date AS date) BETWEEN date '2025-01-01' AND date '2025-12-31'
```

Last 30 days:

```sql
CAST(cr.creation_date AS date) >= date_add('day', -30, current_date)
```

Monthly aggregation:

```sql
date_trunc('month', CAST(cr.creation_date AS date))
```

---

## 7. Demographic data

`demographic_data` may be exposed by Athena as a `ROW`/struct coming from the JSON. If so, you can access the fields with dot notation:

```sql
cr.demographic_data.birth_date
cr.demographic_data.postal_code
cr.demographic_data.sex
cr.demographic_data.nation
```

Known fields from the JSON examples:

| Field | Meaning |
|---|---|
| `birth_date` | Birth date, often `dd.MM.yyyy` |
| `postal_code` | Postal code |
| `sex` | Sex code |
| `nation` | Country/nationality |

Do not assume the meaning of the `sex` code if there is no official dictionary. If the user asks for "men" or "women" and no sex dictionary has been provided, return a query with the raw value only if the user provides the code; otherwise, indicate that the dictionary must be confirmed.

To compute age, use `TRY` because there may be malformed dates:

```sql
WITH base AS (
  SELECT
    cr.id,
    cr.patient_ref,
    TRY(CAST(date_parse(cr.demographic_data.birth_date, '%d.%m.%Y') AS date)) AS birth_date
  FROM datascope_gestor_prod.clinical_reports cr
)
SELECT
  id,
  patient_ref,
  date_diff('year', birth_date, current_date) AS age_years
FROM base
WHERE birth_date IS NOT NULL;
```

---

## 8. Identifying data

`identifiable_data` may include name, surnames, CIP, phone, address, email, DNI, SSN or prosthesis codes.

By default:

- Do not select `first_name`, surnames, phone, address, email, DNI or CIP.
- Return `patient_ref`, `episode_ref` and `id` if clinical traceability is needed.
- If the user explicitly requests identifying data, limit the result and select only the necessary fields.

---

## 9. Correct counting with `UNNEST`

Since each report may have multiple sections, after `UNNEST` one report row becomes several rows. Therefore:

- Count reports: `COUNT(DISTINCT cr.id)`
- Count patients: `COUNT(DISTINCT cr.patient_ref)`
- Count episodes: `COUNT(DISTINCT cr.episode_ref)`
- Return reports without duplicates: `SELECT DISTINCT cr.id, ...`

Incorrect if you want to count reports:

```sql
COUNT(*)
```

Correct:

```sql
COUNT(DISTINCT cr.id)
```

---

## 10. Reusable SQL patterns

### 10.1 Basic text search across all sections

```sql
SELECT DISTINCT
  cr.id AS report_id,
  CAST(cr.creation_date AS date) AS creation_date,
  cr.type AS report_type,
  cr.patient_ref,
  cr.episode_ref,
  sec.section_id,
  substr(sec.section_text, 1, 1000) AS section_snippet
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE regexp_like(
  lower(coalesce(sec.section_text, '')),
  'TERM_OR_REGEX'
)
ORDER BY creation_date DESC
LIMIT 100;
```

### 10.2 Text search in specific sections

```sql
SELECT DISTINCT
  cr.id AS report_id,
  CAST(cr.creation_date AS date) AS creation_date,
  cr.type AS report_type,
  cr.patient_ref,
  cr.episode_ref,
  sec.section_id,
  substr(sec.section_text, 1, 1000) AS section_snippet
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE sec.section_id IN ('MOTIV_CONS', 'PROC_ACTL', 'PROC_ACTL2')
  AND regexp_like(
    lower(coalesce(sec.section_text, '')),
    'TERM_OR_REGEX'
  )
ORDER BY creation_date DESC
LIMIT 100;
```

### 10.3 Counting patients and reports per month

```sql
SELECT
  date_trunc('month', CAST(cr.creation_date AS date)) AS month,
  COUNT(DISTINCT cr.patient_ref) AS patients,
  COUNT(DISTINCT cr.episode_ref) AS episodes,
  COUNT(DISTINCT cr.id) AS reports
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE regexp_like(
  lower(coalesce(sec.section_text, '')),
  'TERM_OR_REGEX'
)
GROUP BY 1
ORDER BY 1;
```

### 10.4 Multiple conditions across different sections of the same report

This pattern is needed when the user asks for reports that meet two conditions, for example "history of diabetes and current process with infection".

```sql
WITH section_flat AS (
  SELECT
    cr.id AS report_id,
    CAST(cr.creation_date AS date) AS creation_date,
    cr.patient_ref,
    cr.episode_ref,
    sec.section_id,
    sec.section_text
  FROM datascope_gestor_prod.clinical_reports cr
  CROSS JOIN UNNEST(cr.sections) AS u(sec)
)
SELECT
  report_id,
  creation_date,
  patient_ref,
  episode_ref
FROM section_flat
GROUP BY
  report_id,
  creation_date,
  patient_ref,
  episode_ref
HAVING
  MAX(
    CASE
      WHEN section_id IN ('ANTEC', 'OTR_ANTPER')
       AND regexp_like(lower(coalesce(section_text, '')), 'diabet')
      THEN 1 ELSE 0
    END
  ) = 1
  AND
  MAX(
    CASE
      WHEN section_id IN ('PROC_ACTL', 'PROC_ACTL2', 'MOTIV_CONS', 'MOTIV_CON2')
       AND regexp_like(lower(coalesce(section_text, '')), 'infecci[oó]|febre|fiebre')
      THEN 1 ELSE 0
    END
  ) = 1
ORDER BY creation_date DESC
LIMIT 100;
```

### 10.5 Return all relevant sections aggregated per report

Useful when you want to provide clinical context without duplicating the report across several rows.

```sql
WITH section_flat AS (
  SELECT
    cr.id AS report_id,
    CAST(cr.creation_date AS date) AS creation_date,
    cr.patient_ref,
    cr.episode_ref,
    sec.section_id,
    sec.section_text,
    section_pos
  FROM datascope_gestor_prod.clinical_reports cr
  CROSS JOIN UNNEST(cr.sections) WITH ORDINALITY AS u(sec, section_pos)
  WHERE sec.section_id IN ('MOTIV_CONS', 'PROC_ACTL', 'PROC_ACTL2', 'TXT_DIAGN', 'ORI_DIAG', 'CONCL')
    AND regexp_like(
      lower(coalesce(sec.section_text, '')),
      'TERM_OR_REGEX'
    )
)
SELECT
  report_id,
  creation_date,
  patient_ref,
  episode_ref,
  array_join(
    array_agg(concat('[', section_id, '] ', section_text) ORDER BY section_pos),
    chr(10)
  ) AS relevant_sections_text
FROM section_flat
GROUP BY
  report_id,
  creation_date,
  patient_ref,
  episode_ref
ORDER BY creation_date DESC
LIMIT 100;
```

### 10.6 Latest version per report, if there are duplicate versions

Use this pattern only if you need to deduplicate versions.

```sql
WITH latest_reports AS (
  SELECT *
  FROM (
    SELECT
      cr.*,
      row_number() OVER (
        PARTITION BY cr.id
        ORDER BY TRY_CAST(cr.version AS integer) DESC
      ) AS rn
    FROM datascope_gestor_prod.clinical_reports cr
  )
  WHERE rn = 1
)
SELECT
  cr.id AS report_id,
  CAST(cr.creation_date AS date) AS creation_date,
  cr.type AS report_type,
  cr.patient_ref,
  cr.episode_ref,
  sec.section_id,
  substr(sec.section_text, 1, 1000) AS section_snippet
FROM latest_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE regexp_like(
  lower(coalesce(sec.section_text, '')),
  'TERM_OR_REGEX'
)
ORDER BY creation_date DESC
LIMIT 100;
```


### 10.7 Filter or group by documentary type (`type`)

If the query only uses report metadata, such as `type` or `creation_date`, you do not need to `UNNEST(sections)`.

Count reports per documentary type:

```sql
SELECT
  cr.type AS report_type,
  COUNT(DISTINCT cr.id) AS reports,
  COUNT(DISTINCT cr.patient_ref) AS patients,
  COUNT(DISTINCT cr.episode_ref) AS episodes
FROM datascope_gestor_prod.clinical_reports cr
GROUP BY cr.type
ORDER BY reports DESC;
```

Filter discharge reports without querying clinical text:

```sql
SELECT DISTINCT
  cr.id AS report_id,
  CAST(cr.creation_date AS date) AS creation_date,
  cr.type AS report_type,
  cr.patient_ref,
  cr.episode_ref
FROM datascope_gestor_prod.clinical_reports cr
WHERE cr.type IN ('IA_ALTA', 'IA_ALTA_EN', 'IA_ALTA_EC', 'IA_ALTA_TE', 'IA_UDT')
ORDER BY creation_date DESC
LIMIT 100;
```

Filter by documentary type and, at the same time, search clinical text within the sections:

```sql
SELECT DISTINCT
  cr.id AS report_id,
  CAST(cr.creation_date AS date) AS creation_date,
  cr.type AS report_type,
  cr.patient_ref,
  cr.episode_ref,
  sec.section_id,
  substr(sec.section_text, 1, 1000) AS section_snippet
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE cr.type = 'IA_ALTA'
  AND regexp_like(
    lower(coalesce(sec.section_text, '')),
    'TERM_OR_REGEX'
  )
ORDER BY creation_date DESC
LIMIT 100;
```

---

## 11. Examples: clinical question → SQL

### Example A: "Find reports with endophthalmitis"

```sql
SELECT DISTINCT
  cr.id AS report_id,
  CAST(cr.creation_date AS date) AS creation_date,
  cr.type AS report_type,
  cr.patient_ref,
  cr.episode_ref,
  sec.section_id,
  substr(sec.section_text, 1, 1000) AS section_snippet
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE regexp_like(
  lower(coalesce(sec.section_text, '')),
  'endoftalmitis|endophthalmitis'
)
ORDER BY creation_date DESC
LIMIT 100;
```

### Example B: "Patients with hearing loss as the reason for consultation"

```sql
SELECT DISTINCT
  cr.patient_ref,
  cr.episode_ref,
  cr.id AS report_id,
  CAST(cr.creation_date AS date) AS creation_date,
  cr.type AS report_type,
  sec.section_id,
  substr(sec.section_text, 1, 1000) AS section_snippet
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE sec.section_id IN ('MOTIV_CONS', 'MOTIV_CON2')
  AND regexp_like(
    lower(coalesce(sec.section_text, '')),
    'hipoacusia|hipoac[uú]sia|p[eé]rdua auditiva|p[eé]rdida auditiva'
  )
ORDER BY creation_date DESC
LIMIT 100;
```

### Example C: "Count reports with chest pain per month"

```sql
SELECT
  date_trunc('month', CAST(cr.creation_date AS date)) AS month,
  COUNT(DISTINCT cr.patient_ref) AS patients,
  COUNT(DISTINCT cr.episode_ref) AS episodes,
  COUNT(DISTINCT cr.id) AS reports
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE sec.section_id IN ('MOTIV_CONS', 'MOTIV_CON2', 'PROC_ACTL', 'PROC_ACTL2', 'TXT_DIAGN', 'ORI_DIAG')
  AND regexp_like(
    lower(coalesce(sec.section_text, '')),
    'dolor tor[aà]cic|dolor toracico|dolor tor[aá]cico|chest pain'
  )
GROUP BY 1
ORDER BY 1;
```

### Example D: "Reports with comments about glomerular filtration"

```sql
SELECT DISTINCT
  cr.id AS report_id,
  CAST(cr.creation_date AS date) AS creation_date,
  cr.type AS report_type,
  cr.patient_ref,
  cr.episode_ref,
  sec.section_id,
  substr(sec.section_text, 1, 1000) AS section_snippet
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE sec.section_id IN ('N2LACOMM', 'EXP_COMPL', 'RESL')
  AND regexp_like(
    lower(coalesce(sec.section_text, '')),
    'filtrat glomerular|fg|ckd-epi|ml/min'
  )
ORDER BY creation_date DESC
LIMIT 100;
```

### Example E: "History of diabetes and therapeutic plan with insulin"

```sql
WITH section_flat AS (
  SELECT
    cr.id AS report_id,
    CAST(cr.creation_date AS date) AS creation_date,
    cr.patient_ref,
    cr.episode_ref,
    sec.section_id,
    sec.section_text
  FROM datascope_gestor_prod.clinical_reports cr
  CROSS JOIN UNNEST(cr.sections) AS u(sec)
)
SELECT
  report_id,
  creation_date,
  patient_ref,
  episode_ref
FROM section_flat
GROUP BY
  report_id,
  creation_date,
  patient_ref,
  episode_ref
HAVING
  MAX(
    CASE
      WHEN section_id IN ('ANTEC', 'OTR_ANTPER')
       AND regexp_like(lower(coalesce(section_text, '')), 'diabet')
      THEN 1 ELSE 0
    END
  ) = 1
  AND
  MAX(
    CASE
      WHEN section_id IN ('PLAN_TER', 'PLAN_TERA', 'IND_ALTA', 'SEGUIMN')
       AND regexp_like(lower(coalesce(section_text, '')), 'insulina|insulin')
      THEN 1 ELSE 0
    END
  ) = 1
ORDER BY creation_date DESC
LIMIT 100;
```


### Example F: "Count reports per document type"

```sql
SELECT
  cr.type AS report_type,
  COUNT(DISTINCT cr.id) AS reports,
  COUNT(DISTINCT cr.patient_ref) AS patients,
  COUNT(DISTINCT cr.episode_ref) AS episodes
FROM datascope_gestor_prod.clinical_reports cr
GROUP BY cr.type
ORDER BY reports DESC;
```

### Example G: "Discharge reports with psychosis"

```sql
SELECT DISTINCT
  cr.id AS report_id,
  CAST(cr.creation_date AS date) AS creation_date,
  cr.type AS report_type,
  cr.patient_ref,
  cr.episode_ref,
  sec.section_id,
  substr(sec.section_text, 1, 1000) AS section_snippet
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
WHERE cr.type IN ('IA_ALTA', 'IA_ALTA_EN', 'IA_ALTA_EC', 'IA_ALTA_TE', 'IA_UDT')
  AND regexp_like(
    lower(coalesce(sec.section_text, '')),
    'psicosi|psicosis|psic[oó]tic|psic[oó]tico|esquizofr[eè]nia|esquizofrenia'
  )
ORDER BY creation_date DESC
LIMIT 100;
```

---

## 12. Recommended chat response format

When the user asks for a query, preferably return:

1. SQL in a single code block.
2. A brief note of assumptions only if needed.

Example:

```sql
SELECT ...
```

Assumptions: I searched the term in the reason for consultation and current process because the user did not specify a particular section.

Do not give long explanations if the user only wants SQL.

---

## 13. Privacy and security best practices

1. Generate only read-only queries (`SELECT`).
2. Do not generate `CREATE`, `DROP`, `DELETE`, `UPDATE`, `INSERT`, `MERGE`, `UNLOAD` or `CTAS` unless there is an explicit technical request and proper authorization.
3. Do not return direct identifying fields by default.
4. Use `LIMIT 100` in exploratory listings.
5. For textual clinical results, return snippets with `substr(sec.section_text, 1, 1000)` if the full text is not needed.
6. In counts or aggregations, avoid exposing free text.
7. Do not infer structured clinical codes that do not exist in the table.
8. Remember that a text search does not equal a confirmed diagnosis: the mention may be a suspicion, a negation, a history item or context.

---

## 14. Checklist before giving the SQL

Before answering, mentally check:

- [ ] I am using `datascope_gestor_prod.clinical_reports`.
- [ ] I am using the Athena/PrestoSQL dialect.
- [ ] If I filter by documentary type, I used `cr.type` and not `sec.section_id`.
- [ ] If I query clinical text, I did `CROSS JOIN UNNEST(cr.sections) AS u(sec)`.
- [ ] I filtered `sec.section_id` only after the `UNNEST`.
- [ ] I searched in `sec.section_text` with `lower(coalesce(...))`.
- [ ] If I count reports/patients/episodes, I use `COUNT(DISTINCT ...)`.
- [ ] I avoided direct identifying fields if they are not necessary.
- [ ] I put `LIMIT` on listing queries.
- [ ] I did not invent columns, tables, `type` codes or meanings of undocumented codes.

---

## 15. Information not available in this table

The `clinical_reports` table mainly contains unstructured clinical text and basic report metadata. The documentary type IS available as a structured field `type`. Do not assume there is structured information about:

- Medical service.
- Responsible professional.
- Coded ICD diagnoses.
- Structured medication.
- Structured laboratory results.
- Coded procedures.
- Hospital location.
- Official dictionary of the `sex` code.

If the user asks about these concepts, do one of two things:

1. If it may appear in free text, propose a text search over `sections`.
2. If it requires reliable structured data, indicate that another table or an additional dictionary would be needed.

---

## 16. Essential summary for the LLM

The most important rule is:

```sql
FROM datascope_gestor_prod.clinical_reports cr
CROSS JOIN UNNEST(cr.sections) AS u(sec)
```

Then:

```sql
WHERE sec.section_id IN (...)
  AND regexp_like(lower(coalesce(sec.section_text, '')), '...')
```

To count:

```sql
COUNT(DISTINCT cr.id)          -- reports
COUNT(DISTINCT cr.patient_ref)         -- patients
COUNT(DISTINCT cr.episode_ref) -- episodes
```

To filter by documentary type, use `cr.type` according to the `type` dictionary. Do not use MariaDB. Do not select identifying data by default.
