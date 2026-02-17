"""Seed the database with a realistic demo political debate session.

Run from the backend directory:
    python -m scripts.seed_demo
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session, engine
from app.models.base import generate_prefixed_id
from app.models.claim import Claim, EvidencePassage, Source, VerdictAuditLog
from app.models.session import Session, TranscriptSegment


async def seed():
    async with async_session() as db:
        # Check if demo session already exists
        result = await db.execute(text("SELECT id FROM sessions WHERE title = 'Demo: 2024 Presidential Debate Excerpt'"))
        if result.scalar_one_or_none():
            print("Demo session already exists. Delete it first or use a fresh database.")
            return

        # --- Session ---
        session = Session(
            id="sess_demo_001",
            title="Demo: 2024 Presidential Debate Excerpt",
            channel_name="PBS NewsHour",
            broadcast_date=datetime(2024, 10, 15, 21, 0, tzinfo=timezone.utc),
            language="en",
            status="completed",
            processing_stage=None,
            progress_pct=100,
            duration_seconds=312,
            completed_at=datetime(2024, 10, 15, 21, 10, tzinfo=timezone.utc),
        )
        db.add(session)
        await db.flush()

        # --- Transcript Segments ---
        segments_data = [
            {
                "id": "seg_demo_001",
                "speaker": "Moderator",
                "text": "Good evening and welcome to the presidential debate. Let's begin with the economy. Candidate A, the unemployment rate — where does it stand?",
                "start_ms": 0,
                "end_ms": 8500,
            },
            {
                "id": "seg_demo_002",
                "speaker": "Candidate A",
                "text": "Thank you. The unemployment rate is at a fifty-year low right now. We've created 15 million new jobs since I took office. The economy has never been stronger.",
                "start_ms": 9000,
                "end_ms": 22000,
            },
            {
                "id": "seg_demo_003",
                "speaker": "Candidate B",
                "text": "That's just not true. Inflation hit 9 percent under this administration, the highest in 40 years. Gas prices doubled. And we spent over two trillion dollars on the infrastructure bill with nothing to show for it.",
                "start_ms": 23000,
                "end_ms": 40000,
            },
            {
                "id": "seg_demo_004",
                "speaker": "Candidate A",
                "text": "Inflation has come down to 2.4 percent. That's a fact. And the infrastructure law is rebuilding 45,000 bridges across America right now.",
                "start_ms": 41000,
                "end_ms": 52000,
            },
            {
                "id": "seg_demo_005",
                "speaker": "Moderator",
                "text": "Let's move to healthcare. Candidate B, your position on the Affordable Care Act?",
                "start_ms": 53000,
                "end_ms": 59000,
            },
            {
                "id": "seg_demo_006",
                "speaker": "Candidate B",
                "text": "Under my plan, prescription drug costs will drop by 50 percent. We'll negotiate directly with pharmaceutical companies. Medicare spending has gone up 30 percent in just four years.",
                "start_ms": 60000,
                "end_ms": 76000,
            },
            {
                "id": "seg_demo_007",
                "speaker": "Candidate A",
                "text": "We already capped insulin at 35 dollars a month for seniors on Medicare. That's saving millions of Americans real money. The Inflation Reduction Act is the biggest climate investment in history.",
                "start_ms": 77000,
                "end_ms": 92000,
            },
            {
                "id": "seg_demo_008",
                "speaker": "Candidate B",
                "text": "This is the worst economy in American history. People can't afford groceries. The national debt has gone up 8 trillion dollars.",
                "start_ms": 93000,
                "end_ms": 105000,
            },
            {
                "id": "seg_demo_009",
                "speaker": "Candidate A",
                "text": "Crime is down 12 percent nationwide according to the FBI. We've added 800,000 manufacturing jobs. America is leading the world again.",
                "start_ms": 106000,
                "end_ms": 118000,
            },
            {
                "id": "seg_demo_010",
                "speaker": "Moderator",
                "text": "We'll take a short break and return with questions on foreign policy and immigration.",
                "start_ms": 119000,
                "end_ms": 125000,
            },
        ]

        for seg in segments_data:
            ts = TranscriptSegment(
                id=seg["id"],
                session_id=session.id,
                speaker_label=seg["speaker"],
                text=seg["text"],
                start_ms=seg["start_ms"],
                end_ms=seg["end_ms"],
            )
            db.add(ts)

        await db.flush()

        # --- Sources ---
        sources = [
            Source(
                id="src_demo_bls",
                url="https://data.bls.gov/timeseries/LNS14000000",
                title="Labor Force Statistics — Unemployment Rate",
                publisher="U.S. Bureau of Labor Statistics",
                source_tier="tier_1_government_primary",
                content_text="U.S. unemployment rate (seasonally adjusted): Sep 2024: 4.1%, Aug 2024: 4.2%, Jul 2024: 4.3%, Jun 2024: 4.0%, Jan 2023: 3.4% (lowest since May 1969 at 3.4%), Dec 1969: 3.5%.",
                verification_status="active",
            ),
            Source(
                id="src_demo_bls_jobs",
                url="https://data.bls.gov/timeseries/CES0000000001",
                title="Total Nonfarm Payroll Employment",
                publisher="U.S. Bureau of Labor Statistics",
                source_tier="tier_1_government_primary",
                content_text="Total nonfarm payroll employment increased by approximately 16.1 million from January 2021 through September 2024, from 142.7 million to 158.8 million.",
                verification_status="active",
            ),
            Source(
                id="src_demo_cpi",
                url="https://data.bls.gov/timeseries/CUUR0000SA0",
                title="Consumer Price Index — All Urban Consumers",
                publisher="U.S. Bureau of Labor Statistics",
                source_tier="tier_1_government_primary",
                content_text="CPI-U 12-month percent change: Jun 2022: 9.1% (highest since Nov 1981 at 10.3%), Sep 2024: 2.4%, Aug 2024: 2.5%.",
                verification_status="active",
            ),
            Source(
                id="src_demo_eia",
                url="https://www.eia.gov/petroleum/gasdiesel/",
                title="Weekly Retail Gasoline and Diesel Prices",
                publisher="U.S. Energy Information Administration",
                source_tier="tier_1_government_primary",
                content_text="Average regular gasoline price: Jan 2021: $2.33/gal, Jun 2022 peak: $5.02/gal (highest recorded), Oct 2024: $3.21/gal.",
                verification_status="active",
            ),
            Source(
                id="src_demo_iija",
                url="https://www.congress.gov/bill/117th-congress/house-bill/3684",
                title="H.R.3684 — Infrastructure Investment and Jobs Act",
                publisher="Congress.gov",
                source_tier="tier_1_government_primary",
                content_text="Signed into law November 15, 2021. Total authorization: approximately $1.2 trillion over 5 years, including $550 billion in new federal spending for roads, bridges, broadband, water, transit, rail, airports, ports, and EV infrastructure.",
                verification_status="active",
            ),
            Source(
                id="src_demo_bridges",
                url="https://www.whitehouse.gov/briefing-room/statements-releases/2024/infrastructure-progress/",
                title="Infrastructure Investment Progress Report",
                publisher="White House",
                source_tier="tier_1_government_primary",
                content_text="As of September 2024, 7,800 bridge repair projects have been announced using IIJA funds. The total number of structurally deficient bridges in the US is approximately 42,000 per FHWA data, not 45,000.",
                verification_status="active",
            ),
            Source(
                id="src_demo_ira",
                url="https://www.congress.gov/bill/117th-congress/house-bill/5376",
                title="H.R.5376 — Inflation Reduction Act of 2022",
                publisher="Congress.gov",
                source_tier="tier_1_government_primary",
                content_text="Signed into law August 16, 2022. Includes approximately $369 billion in energy security and climate investments over 10 years. Caps insulin copay at $35/month for Medicare Part D beneficiaries starting January 2023.",
                verification_status="active",
            ),
            Source(
                id="src_demo_insulin",
                url="https://www.cms.gov/newsroom/fact-sheets/inflation-reduction-act-insulin",
                title="Inflation Reduction Act and Insulin",
                publisher="Centers for Medicare & Medicaid Services",
                source_tier="tier_1_government_primary",
                content_text="Beginning January 1, 2023, the Inflation Reduction Act caps monthly insulin cost-sharing at $35 for people with Medicare. In 2023, approximately 1.5 million Medicare Part D enrollees used insulin. The cap does not currently apply to the commercial/employer insurance market.",
                verification_status="active",
            ),
            Source(
                id="src_demo_debt",
                url="https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/",
                title="Debt to the Penny",
                publisher="U.S. Department of the Treasury",
                source_tier="tier_1_government_primary",
                content_text="Total public debt outstanding: Jan 20, 2021: $27.75 trillion. Oct 1, 2024: $35.67 trillion. Increase under current administration: approximately $7.92 trillion.",
                verification_status="active",
            ),
            Source(
                id="src_demo_fbi",
                url="https://cde.ucr.cjis.gov/LATEST/webapp/#/pages/home",
                title="Crime Data Explorer",
                publisher="Federal Bureau of Investigation",
                source_tier="tier_1_government_primary",
                content_text="FBI Uniform Crime Report (preliminary 2024 data): Overall violent crime down approximately 5.7% in first half of 2024 compared to first half of 2023. Property crime down 7.1%. Full 2024 year-over-year data not yet available.",
                verification_status="active",
            ),
            Source(
                id="src_demo_mfg",
                url="https://data.bls.gov/timeseries/CES3000000001",
                title="Manufacturing Employment",
                publisher="U.S. Bureau of Labor Statistics",
                source_tier="tier_1_government_primary",
                content_text="Manufacturing employment: Jan 2021: 12.23 million. Sep 2024: 12.87 million. Net gain: approximately 640,000, not 800,000 as claimed.",
                verification_status="active",
            ),
            Source(
                id="src_demo_cms_medicare",
                url="https://www.cms.gov/data-research/statistics-trends-and-reports/national-health-expenditure-data",
                title="National Health Expenditure Data",
                publisher="Centers for Medicare & Medicaid Services",
                source_tier="tier_1_government_primary",
                content_text="Medicare spending: 2020: $829.5 billion, 2021: $900.8 billion, 2022: $944.3 billion, 2023: $1,009.8 billion (estimated). Four-year increase from 2020-2023: approximately 21.7%, not 30%.",
                verification_status="active",
            ),
            Source(
                id="src_demo_climate",
                url="https://www.iea.org/reports/world-energy-investment-2024",
                title="World Energy Investment 2024",
                publisher="International Energy Agency",
                source_tier="tier_2_court_academic",
                content_text="The U.S. Inflation Reduction Act represents the largest single climate investment by any country in history, with an estimated $369 billion in energy security and climate provisions. The EU Green Deal Industrial Plan and China's clean energy subsidies are comparable in scale but structured differently.",
                verification_status="active",
            ),
        ]

        for src in sources:
            db.add(src)
        await db.flush()

        # --- Claims + Verdicts + Evidence ---
        claims_data = [
            # Claim 1: Unemployment at fifty-year low
            {
                "id": "clm_demo_001",
                "text": "The unemployment rate is at a fifty-year low right now.",
                "normalized": {
                    "subject": "U.S. unemployment rate",
                    "predicate": "is at",
                    "object": "fifty-year low",
                    "qualifiers": ["as of date of statement"],
                },
                "time_scope": {"is_current": True, "ambiguity_notes": "'Right now' — date of broadcast: 2024-10-15"},
                "location_scope": "United States",
                "speaker": "Candidate A",
                "start_ms": 9000,
                "end_ms": 22000,
                "claim_type": "checkable_fact",
                "worthiness": 0.94,
                "evidence_types": ["primary_government_data"],
                "verdict": "HALF_TRUE",
                "confidence": 0.82,
                "summary": "The rate hit a 50-year low of 3.4% in Jan 2023, but as of Oct 2024 it is 4.1% — no longer a 50-year low.",
                "bullets": [
                    "BLS data shows U.S. unemployment was 3.4% in January 2023, the lowest since May 1969 [SOURCE_1].",
                    "As of September 2024, the rate is 4.1% — significantly above the 50-year low [SOURCE_1].",
                    "The claim was accurate 21 months ago but is not accurate 'right now.'",
                ],
                "what_would_change": "If a more recent BLS release showed the rate dropping back below 3.5%, this would shift toward TRUE.",
                "evidence": [
                    {"source_id": "src_demo_bls", "snippet": "Sep 2024: 4.1%, Jan 2023: 3.4% (lowest since May 1969)", "relevance": "contradicts", "score": 0.95},
                ],
            },
            # Claim 2: Created 15 million new jobs
            {
                "id": "clm_demo_002",
                "text": "We've created 15 million new jobs since I took office.",
                "normalized": {
                    "subject": "Current administration",
                    "predicate": "created",
                    "object": "15 million new jobs",
                    "qualifiers": ["since taking office"],
                },
                "time_scope": {"start_date": "2021-01-20", "is_current": True},
                "location_scope": "United States",
                "speaker": "Candidate A",
                "start_ms": 9000,
                "end_ms": 22000,
                "claim_type": "checkable_fact",
                "worthiness": 0.91,
                "evidence_types": ["primary_government_data"],
                "verdict": "MOSTLY_TRUE",
                "confidence": 0.78,
                "summary": "BLS data shows ~16.1 million jobs added since Jan 2021, actually exceeding the 15 million claim.",
                "bullets": [
                    "Total nonfarm payrolls increased by approximately 16.1 million from Jan 2021 to Sep 2024 [SOURCE_1].",
                    "The '15 million' figure understates the actual gain, making the claim directionally correct.",
                    "Note: Much of early job growth was pandemic recovery, not net new job creation above pre-pandemic levels.",
                ],
                "what_would_change": "Adjusting for pandemic recovery (jobs that were lost and regained) would give a different picture of 'created' vs 'recovered.'",
                "evidence": [
                    {"source_id": "src_demo_bls_jobs", "snippet": "Nonfarm payrolls increased ~16.1 million from Jan 2021 to Sep 2024", "relevance": "supports", "score": 0.92},
                ],
            },
            # Claim 3: Inflation hit 9 percent, highest in 40 years
            {
                "id": "clm_demo_003",
                "text": "Inflation hit 9 percent under this administration, the highest in 40 years.",
                "normalized": {
                    "subject": "U.S. inflation rate",
                    "predicate": "reached",
                    "object": "9 percent, highest in 40 years",
                    "qualifiers": ["under current administration"],
                },
                "time_scope": {"start_date": "2021-01-20", "is_current": True},
                "location_scope": "United States",
                "speaker": "Candidate B",
                "start_ms": 23000,
                "end_ms": 40000,
                "claim_type": "checkable_fact",
                "worthiness": 0.95,
                "evidence_types": ["primary_government_data"],
                "verdict": "TRUE",
                "confidence": 0.93,
                "summary": "CPI-U hit 9.1% year-over-year in June 2022, the highest since November 1981 (10.3%) — over 40 years prior.",
                "bullets": [
                    "CPI-U 12-month percent change peaked at 9.1% in June 2022 [SOURCE_1].",
                    "The previous comparable peak was 10.3% in November 1981, approximately 41 years earlier [SOURCE_1].",
                    "The claim of '9 percent' slightly understates the actual 9.1% peak, and 'highest in 40 years' is accurate (41 years).",
                ],
                "what_would_change": "This is a factual historical record and unlikely to change.",
                "evidence": [
                    {"source_id": "src_demo_cpi", "snippet": "Jun 2022: 9.1% (highest since Nov 1981 at 10.3%)", "relevance": "supports", "score": 0.97},
                ],
            },
            # Claim 4: Gas prices doubled
            {
                "id": "clm_demo_004",
                "text": "Gas prices doubled.",
                "normalized": {
                    "subject": "U.S. gasoline prices",
                    "predicate": "doubled",
                    "object": "from baseline",
                    "qualifiers": ["implied: during current administration"],
                },
                "time_scope": {"start_date": "2021-01-20", "is_current": True},
                "location_scope": "United States",
                "speaker": "Candidate B",
                "start_ms": 23000,
                "end_ms": 40000,
                "claim_type": "checkable_fact",
                "worthiness": 0.85,
                "evidence_types": ["primary_government_data"],
                "verdict": "MOSTLY_TRUE",
                "confidence": 0.80,
                "summary": "Gas prices went from $2.33 to a $5.02 peak (more than double) but have since fallen to $3.21.",
                "bullets": [
                    "Average regular gas was $2.33/gal in Jan 2021 and peaked at $5.02/gal in Jun 2022 — a 115% increase, more than double [SOURCE_1].",
                    "As of Oct 2024, prices are $3.21/gal — 38% above the Jan 2021 level but well below the peak [SOURCE_1].",
                    "The claim is accurate for the peak period but misleading about current prices.",
                ],
                "what_would_change": "If the claim specified 'at the peak,' it would be fully TRUE. Current prices have not doubled.",
                "evidence": [
                    {"source_id": "src_demo_eia", "snippet": "Jan 2021: $2.33/gal, Jun 2022 peak: $5.02/gal, Oct 2024: $3.21/gal", "relevance": "partially_supports", "score": 0.90},
                ],
            },
            # Claim 5: Spent over two trillion on infrastructure bill
            {
                "id": "clm_demo_005",
                "text": "We spent over two trillion dollars on the infrastructure bill with nothing to show for it.",
                "normalized": {
                    "subject": "U.S. federal government",
                    "predicate": "spent",
                    "object": "over $2 trillion on infrastructure bill",
                    "qualifiers": ["'spent' vs 'authorized' ambiguity"],
                },
                "time_scope": {"start_date": "2021-11-15"},
                "location_scope": "United States",
                "speaker": "Candidate B",
                "start_ms": 23000,
                "end_ms": 40000,
                "claim_type": "checkable_fact",
                "worthiness": 0.91,
                "evidence_types": ["primary_government_data", "legislative_record"],
                "verdict": "MOSTLY_FALSE",
                "confidence": 0.85,
                "summary": "The IIJA authorized $1.2 trillion (not $2T). The speaker may be conflating it with the Build Back Better proposal.",
                "bullets": [
                    "The Infrastructure Investment and Jobs Act authorized approximately $1.2 trillion total, with ~$550 billion in new spending [SOURCE_1].",
                    "No infrastructure legislation authorized or spent 'over $2 trillion' [SOURCE_1].",
                    "The separate Build Back Better Act proposed ~$1.75 trillion but was never passed in that form.",
                    "'Nothing to show for it' is contradicted by 7,800 bridge projects announced [SOURCE_2].",
                ],
                "what_would_change": "If the speaker clarified they meant total infrastructure spending across multiple bills, a broader analysis would be needed.",
                "evidence": [
                    {"source_id": "src_demo_iija", "snippet": "Total authorization: $1.2 trillion including $550 billion in new federal investment", "relevance": "contradicts", "score": 0.95},
                    {"source_id": "src_demo_bridges", "snippet": "7,800 bridge repair projects announced using IIJA funds", "relevance": "contradicts", "score": 0.80},
                ],
            },
            # Claim 6: Inflation has come down to 2.4 percent
            {
                "id": "clm_demo_006",
                "text": "Inflation has come down to 2.4 percent.",
                "normalized": {
                    "subject": "U.S. inflation rate",
                    "predicate": "has decreased to",
                    "object": "2.4 percent",
                    "qualifiers": [],
                },
                "time_scope": {"is_current": True},
                "location_scope": "United States",
                "speaker": "Candidate A",
                "start_ms": 41000,
                "end_ms": 52000,
                "claim_type": "checkable_fact",
                "worthiness": 0.88,
                "evidence_types": ["primary_government_data"],
                "verdict": "TRUE",
                "confidence": 0.95,
                "summary": "CPI-U 12-month change was 2.4% as of September 2024, matching the claim exactly.",
                "bullets": [
                    "BLS data shows CPI-U 12-month percent change was 2.4% in September 2024 [SOURCE_1].",
                    "This represents a significant decline from the 9.1% peak in June 2022 [SOURCE_1].",
                    "The claim is factually accurate as of the most recent data.",
                ],
                "what_would_change": "If the October 2024 CPI release shows a significant increase, the 'has come down to' framing may become less accurate.",
                "evidence": [
                    {"source_id": "src_demo_cpi", "snippet": "Sep 2024: 2.4%", "relevance": "supports", "score": 0.98},
                ],
            },
            # Claim 7: Rebuilding 45,000 bridges
            {
                "id": "clm_demo_007",
                "text": "The infrastructure law is rebuilding 45,000 bridges across America right now.",
                "normalized": {
                    "subject": "Infrastructure Investment and Jobs Act",
                    "predicate": "is rebuilding",
                    "object": "45,000 bridges",
                    "qualifiers": ["across America", "currently"],
                },
                "time_scope": {"is_current": True},
                "location_scope": "United States",
                "speaker": "Candidate A",
                "start_ms": 41000,
                "end_ms": 52000,
                "claim_type": "checkable_fact",
                "worthiness": 0.87,
                "evidence_types": ["primary_government_data"],
                "verdict": "MOSTLY_FALSE",
                "confidence": 0.77,
                "summary": "7,800 bridge projects announced (not 45,000). The 42,000 figure refers to the total number of structurally deficient bridges.",
                "bullets": [
                    "As of Sep 2024, 7,800 bridge repair projects have been announced using IIJA funds [SOURCE_1].",
                    "The total number of structurally deficient bridges in the US is approximately 42,000 per FHWA data [SOURCE_1].",
                    "The speaker appears to be conflating the total number of deficient bridges with the number being actively repaired.",
                ],
                "what_would_change": "If the administration announced projects covering 45,000+ bridges, this would shift to TRUE.",
                "evidence": [
                    {"source_id": "src_demo_bridges", "snippet": "7,800 bridge repair projects announced; ~42,000 structurally deficient bridges total", "relevance": "contradicts", "score": 0.88},
                    {"source_id": "src_demo_iija", "snippet": "IIJA includes funding for roads, bridges, broadband, water, transit", "relevance": "provides_context", "score": 0.60},
                ],
            },
            # Claim 8: Medicare spending up 30%
            {
                "id": "clm_demo_008",
                "text": "Medicare spending has gone up 30 percent in just four years.",
                "normalized": {
                    "subject": "Medicare spending",
                    "predicate": "increased",
                    "object": "30 percent in four years",
                    "qualifiers": ["implied 2020-2024"],
                },
                "time_scope": {"start_date": "2020-01-01", "end_date": "2024-01-01"},
                "location_scope": "United States",
                "speaker": "Candidate B",
                "start_ms": 60000,
                "end_ms": 76000,
                "claim_type": "checkable_fact",
                "worthiness": 0.89,
                "evidence_types": ["primary_government_data"],
                "verdict": "MOSTLY_FALSE",
                "confidence": 0.75,
                "summary": "Medicare spending rose ~21.7% from 2020-2023, not 30%. The 30% figure overstates the actual increase.",
                "bullets": [
                    "CMS data shows Medicare spending went from $829.5B (2020) to ~$1,009.8B (2023), a 21.7% increase [SOURCE_1].",
                    "The claimed 30% overstates the actual increase by approximately 8 percentage points [SOURCE_1].",
                    "Note: 2024 final data not yet available; even with projected growth, 30% is unlikely to be reached.",
                ],
                "what_would_change": "If 2024 final Medicare spending data shows a large jump, the four-year increase could approach 30%.",
                "evidence": [
                    {"source_id": "src_demo_cms_medicare", "snippet": "2020: $829.5B, 2023: ~$1,009.8B, four-year increase approximately 21.7%", "relevance": "contradicts", "score": 0.88},
                ],
            },
            # Claim 9: Capped insulin at $35/month
            {
                "id": "clm_demo_009",
                "text": "We already capped insulin at 35 dollars a month for seniors on Medicare.",
                "normalized": {
                    "subject": "Current administration / IRA",
                    "predicate": "capped",
                    "object": "insulin cost at $35/month for Medicare seniors",
                    "qualifiers": [],
                },
                "time_scope": {"start_date": "2023-01-01", "is_current": True},
                "location_scope": "United States",
                "speaker": "Candidate A",
                "start_ms": 77000,
                "end_ms": 92000,
                "claim_type": "checkable_fact",
                "worthiness": 0.90,
                "evidence_types": ["primary_government_data", "legislative_record"],
                "verdict": "TRUE",
                "confidence": 0.94,
                "summary": "The Inflation Reduction Act caps insulin copay at $35/month for Medicare Part D enrollees, effective Jan 2023.",
                "bullets": [
                    "The IRA caps monthly insulin cost-sharing at $35 for people with Medicare, effective January 1, 2023 [SOURCE_1].",
                    "Approximately 1.5 million Medicare Part D enrollees used insulin in 2023 [SOURCE_1].",
                    "Note: The cap applies to Medicare beneficiaries only, not the commercial insurance market [SOURCE_1].",
                ],
                "what_would_change": "If the cap were repealed or the speaker implied it applies to all Americans (not just Medicare), the rating would change.",
                "evidence": [
                    {"source_id": "src_demo_insulin", "snippet": "IRA caps monthly insulin at $35 for Medicare enrollees, effective Jan 2023", "relevance": "supports", "score": 0.96},
                    {"source_id": "src_demo_ira", "snippet": "Caps insulin copay at $35/month for Medicare Part D beneficiaries", "relevance": "supports", "score": 0.93},
                ],
            },
            # Claim 10: IRA is biggest climate investment in history
            {
                "id": "clm_demo_010",
                "text": "The Inflation Reduction Act is the biggest climate investment in history.",
                "normalized": {
                    "subject": "Inflation Reduction Act",
                    "predicate": "is",
                    "object": "biggest climate investment in history",
                    "qualifiers": ["implied: by any single country"],
                },
                "time_scope": {"is_current": True},
                "location_scope": "Global",
                "speaker": "Candidate A",
                "start_ms": 77000,
                "end_ms": 92000,
                "claim_type": "checkable_fact",
                "worthiness": 0.86,
                "evidence_types": ["primary_government_data", "academic_study"],
                "verdict": "TRUE",
                "confidence": 0.88,
                "summary": "The IRA's ~$369B in climate provisions is widely recognized as the largest single-country climate investment in history.",
                "bullets": [
                    "The IRA includes approximately $369 billion in energy security and climate investments [SOURCE_1].",
                    "The IEA and multiple independent analyses identify this as the largest single climate investment by any country [SOURCE_2].",
                    "The EU Green Deal and China's programs are comparable but structured differently (across multiple laws/subsidies) [SOURCE_2].",
                ],
                "what_would_change": "If another country passed a larger single climate bill, or if 'history' is interpreted to include cumulative multi-law programs.",
                "evidence": [
                    {"source_id": "src_demo_ira", "snippet": "~$369 billion in energy security and climate investments over 10 years", "relevance": "supports", "score": 0.92},
                    {"source_id": "src_demo_climate", "snippet": "Largest single climate investment by any country in history per IEA", "relevance": "supports", "score": 0.85},
                ],
            },
            # Claim 11: Worst economy in American history (value judgment)
            {
                "id": "clm_demo_011",
                "text": "This is the worst economy in American history.",
                "normalized": {
                    "subject": "Current U.S. economy",
                    "predicate": "is",
                    "object": "worst in American history",
                    "qualifiers": [],
                },
                "time_scope": {"is_current": True},
                "location_scope": "United States",
                "speaker": "Candidate B",
                "start_ms": 93000,
                "end_ms": 105000,
                "claim_type": "value_judgment",
                "worthiness": 0.35,
                "evidence_types": ["primary_government_data"],
                "verdict": "UNVERIFIED",
                "confidence": None,
                "summary": "This is a subjective value judgment. By standard economic metrics, the current economy does not rank as the 'worst.'",
                "bullets": [
                    "Tagged as value judgment — not rated TRUE/FALSE.",
                    "Context: GDP growth is positive, unemployment is 4.1%, inflation has fallen to 2.4%.",
                    "Historical comparisons: Great Depression unemployment peaked at 24.9%; 2008 crisis saw GDP contract 4.3%.",
                ],
                "what_would_change": "N/A — opinions and value judgments are not assigned truth values.",
                "evidence": [],
            },
            # Claim 12: National debt up $8 trillion
            {
                "id": "clm_demo_012",
                "text": "The national debt has gone up 8 trillion dollars.",
                "normalized": {
                    "subject": "U.S. national debt",
                    "predicate": "increased by",
                    "object": "$8 trillion",
                    "qualifiers": ["implied: under current administration"],
                },
                "time_scope": {"start_date": "2021-01-20", "is_current": True},
                "location_scope": "United States",
                "speaker": "Candidate B",
                "start_ms": 93000,
                "end_ms": 105000,
                "claim_type": "checkable_fact",
                "worthiness": 0.92,
                "evidence_types": ["primary_government_data"],
                "verdict": "MOSTLY_TRUE",
                "confidence": 0.82,
                "summary": "Treasury data shows the debt increased ~$7.92 trillion since Jan 2021 — close to but slightly under the $8T claim.",
                "bullets": [
                    "Total public debt: $27.75T (Jan 20, 2021) to $35.67T (Oct 1, 2024), an increase of ~$7.92 trillion [SOURCE_1].",
                    "The $8 trillion figure is a slight overstatement by ~$80 billion, or about 1% [SOURCE_1].",
                    "The claim is directionally accurate and within reasonable rounding.",
                ],
                "what_would_change": "By end of fiscal year 2025, the cumulative increase will likely exceed $8 trillion, making the claim fully accurate.",
                "evidence": [
                    {"source_id": "src_demo_debt", "snippet": "Debt increased from $27.75T to $35.67T (~$7.92T increase)", "relevance": "partially_supports", "score": 0.93},
                ],
            },
            # Claim 13: Crime down 12 percent
            {
                "id": "clm_demo_013",
                "text": "Crime is down 12 percent nationwide according to the FBI.",
                "normalized": {
                    "subject": "U.S. crime rate",
                    "predicate": "decreased",
                    "object": "12 percent",
                    "qualifiers": ["nationwide", "per FBI data"],
                },
                "time_scope": {"is_current": True},
                "location_scope": "United States",
                "speaker": "Candidate A",
                "start_ms": 106000,
                "end_ms": 118000,
                "claim_type": "checkable_fact",
                "worthiness": 0.88,
                "evidence_types": ["primary_government_data"],
                "verdict": "MOSTLY_FALSE",
                "confidence": 0.72,
                "summary": "FBI preliminary data shows violent crime down ~5.7% and property crime down 7.1% in 2024 — not 12% for 'crime' overall.",
                "bullets": [
                    "FBI preliminary 2024 data shows violent crime down ~5.7% and property crime down ~7.1% [SOURCE_1].",
                    "No FBI metric shows an overall 12% decline [SOURCE_1].",
                    "The speaker overstates the decline by roughly double and attributes it vaguely to 'the FBI' without specifying which metric.",
                ],
                "what_would_change": "If full-year 2024 FBI data shows a larger decline, or if a specific crime category dropped 12%+, this could shift.",
                "evidence": [
                    {"source_id": "src_demo_fbi", "snippet": "Violent crime down ~5.7%, property crime down ~7.1% (H1 2024 vs H1 2023)", "relevance": "contradicts", "score": 0.85},
                ],
            },
            # Claim 14: Added 800,000 manufacturing jobs
            {
                "id": "clm_demo_014",
                "text": "We've added 800,000 manufacturing jobs.",
                "normalized": {
                    "subject": "Current administration",
                    "predicate": "added",
                    "object": "800,000 manufacturing jobs",
                    "qualifiers": [],
                },
                "time_scope": {"start_date": "2021-01-20", "is_current": True},
                "location_scope": "United States",
                "speaker": "Candidate A",
                "start_ms": 106000,
                "end_ms": 118000,
                "claim_type": "checkable_fact",
                "worthiness": 0.90,
                "evidence_types": ["primary_government_data"],
                "verdict": "MOSTLY_FALSE",
                "confidence": 0.80,
                "summary": "BLS data shows ~640,000 manufacturing jobs added since Jan 2021, not 800,000.",
                "bullets": [
                    "Manufacturing employment: 12.23M (Jan 2021) to 12.87M (Sep 2024), a gain of ~640,000 [SOURCE_1].",
                    "The claimed 800,000 overstates the actual gain by approximately 160,000 (25% overstatement) [SOURCE_1].",
                    "The trend is real but the specific number is inaccurate.",
                ],
                "what_would_change": "If revised BLS data or a broader definition of manufacturing-related jobs closes the gap.",
                "evidence": [
                    {"source_id": "src_demo_mfg", "snippet": "Manufacturing employment: Jan 2021: 12.23M, Sep 2024: 12.87M, net gain ~640,000", "relevance": "contradicts", "score": 0.90},
                ],
            },
        ]

        for cd in claims_data:
            claim = Claim(
                id=cd["id"],
                session_id=session.id,
                claim_text=cd["text"],
                normalized_claim=cd["normalized"],
                time_scope=cd["time_scope"],
                location_scope=cd.get("location_scope"),
                speaker_label=cd["speaker"],
                start_ms=cd["start_ms"],
                end_ms=cd["end_ms"],
                claim_type=cd["claim_type"],
                claim_worthiness_score=cd["worthiness"],
                required_evidence_types=cd["evidence_types"],
                verdict_label=cd["verdict"],
                verdict_confidence=cd["confidence"],
                verdict_rationale_summary=cd["summary"],
                verdict_rationale_bullets=cd["bullets"],
                verdict_version=1,
                verdict_model_used="demo-seed",
                verdict_generated_at=datetime(2024, 10, 15, 21, 10, tzinfo=timezone.utc),
                what_would_change_verdict=cd["what_would_change"],
            )
            db.add(claim)
            await db.flush()

            # Evidence passages
            for ev in cd["evidence"]:
                passage = EvidencePassage(
                    claim_id=cd["id"],
                    source_id=ev["source_id"],
                    snippet=ev["snippet"],
                    relevance_to_claim=ev["relevance"],
                    relevance_score=ev["score"],
                    retrieval_method="demo-seed",
                )
                db.add(passage)

            # Audit log
            audit = VerdictAuditLog(
                claim_id=cd["id"],
                version=1,
                verdict_label=cd["verdict"],
                confidence=cd["confidence"],
                rationale_summary=cd["summary"],
                rationale_bullets=cd["bullets"],
                model_used="demo-seed",
                evidence_ids=[ev["source_id"] for ev in cd["evidence"]],
            )
            db.add(audit)

        await db.commit()
        print(f"Seeded demo session: {session.id}")
        print(f"  - {len(segments_data)} transcript segments")
        print(f"  - {len(claims_data)} claims with verdicts")
        print(f"  - {len(sources)} sources")
        print("  - Verdict distribution:")
        from collections import Counter
        verdicts = Counter(cd["verdict"] for cd in claims_data)
        for label, count in verdicts.most_common():
            print(f"    {label}: {count}")


if __name__ == "__main__":
    asyncio.run(seed())
