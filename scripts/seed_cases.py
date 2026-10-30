#!/usr/bin/env python3
"""
seed_cases.py — MT Legal Case Seeder
Usage: python scripts/seed_cases.py [--force]

Creates two new full-detail client cases (RHollister, LChen) and enriches
two existing clients (BobbyT, DerekW) with realistic case histories.
Idempotent: skips clients already seeded/enriched unless --force is passed.
"""
import sys, os, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
import app

FORCE = "--force" in sys.argv


# ── Helpers ───────────────────────────────────────────────────────────────────

def E(date, hours, category, note):
    """Build a billing log entry."""
    return {"date": date, "hours": hours, "category": category, "note": note}

def M(from_, date, text):
    """Build a message dict."""
    return {"from": from_, "date": date, "text": text}

def P(amount, method, date, note):
    """Build a payment dict."""
    return {"amount": amount, "method": method, "date": date, "note": note}

def hours_from_log(log):
    return round(sum(float(e.get("hours", 0) or 0) for e in log), 2)

def apply_payments(client, payments):
    for p in payments:
        client.setdefault("payments", []).append(p)
        hrs = round(p["amount"] / app.HOURLY_RATE, 2)
        client["hours_paid"] = round(client.get("hours_paid", 0) + hrs, 2)
        client.setdefault("billing_log", []).append(
            E(p["date"], 0, "Overhead", f"PAYMENT RECEIVED \u2014 {p['note']}")
        )


# ─────────────────────────────────────────────────────────────────────────────
# CASE 1: Raymond T. Hollister — Criminal Defense — Endocide
# Davidson Co. Cr. Case No. 2026-CR-44821
# Outcome: Breathalyzer suppressed; plea to misdemeanor DUI, case closed
# ─────────────────────────────────────────────────────────────────────────────

HOLLISTER_BILLING = [
    E("2026-01-10", 0,   "Intake",           "INTAKE \u2014 Criminal Defense.\nMatter: Felony DUI with refusal, .18 BAC, prior DUI 6 years ago. Davidson Co. Cr. Case No. 2026-CR-44821. Client released on $2,500 bond. Assigned to Madison T. Biggs, Esq."),
    E("2026-01-10", 0.5, "Meeting",          "Initial consultation \u2014 reviewed arrest report, bond conditions, prior conviction record. Explained suppression strategy re: officer certification and breathalyzer calibration. Confirmed retainer agreement signed."),
    E("2026-01-12", 1.0, "Research",         "TCA \u00a7 55-10-401 and .402 research; reviewed implied consent statute; submitted public records request for officer Cpl. Derek Sloan\u2019s certification and breathalyzer maintenance logs. Opposing counsel: ADA Priya Mehta, Davidson Co. DA\u2019s Office."),
    E("2026-01-15", 0.5, "Filing",           "Filed Motion for Preservation of Evidence and initial discovery request with Davidson Co. Criminal Court. Case assigned to Hon. Calvin Reese, Division IV."),
    E("2026-01-20", 0.3, "Phone/Email",      "Call with client re: DMV implied consent hearing. Filed timely request for administrative hearing to contest 1-year license revocation. Client is anxious about driving restriction \u2014 advised patience."),
    E("2026-01-28", 1.0, "Research",         "Discovery returned. Found Cpl. Sloan\u2019s SFST certification expired Feb 2025 \u2014 9 months before arrest. See State v. Bishop, 431 S.W.3d 22 (Tenn. Ct. App. 2013): uncertified officer administration of SFSTs undermines admissibility. Drafted motion to suppress field sobriety tests."),
    E("2026-02-03", 0.5, "Drafting",         "Drafted Motion to Suppress Field Sobriety Tests based on Cpl. Sloan\u2019s lapsed certification. Cited State v. Bishop and State v. Turner, 297 S.W.3d 155 (Tenn. 2009). Filed with Div. IV clerk."),
    E("2026-02-10", 0.5, "Phone/Email",      "Email exchange with ADA Mehta re: discovery supplement. She disclosed Intoxilyzer 9000 maintenance logs. Noted last calibration was 47 days before arrest \u2014 TCA \u00a7 55-10-408 requires calibration every 45 days. Potential breathalyzer suppression angle."),
    E("2026-02-14", 2.0, "Court Appearance", "First suppression hearing before Judge Reese. Argued SFST suppression \u2014 Mehta countered that FST results were merely corroborative. Judge reserved ruling pending supplemental briefs on breathalyzer calibration. See State v. Sensing, 843 S.W.2d 412 (Tenn. 1992) re: breathalyzer foundational requirements."),
    E("2026-02-18", 0.5, "Research",         "Confirmed calibration defect: Intoxilyzer 9000 S/N #4471 last calibrated Jan 3, 2026 \u2014 arrest Feb 19, 2026 = 47 days. TCA \u00a7 55-10-408(a)(1) requires \u226445 days. State v. Sensing foundational requirement not met. Prepared supplemental motion."),
    E("2026-02-20", 0.5, "Drafting",         "Filed Supplemental Motion to Suppress breathalyzer result (.18 BAC). Argued calibration gap violates TCA \u00a7 55-10-408 and State v. Sensing foundational requirements. Without the BAC reading, State has weak case on aggravated DUI element."),
    E("2026-02-24", 1.5, "Court Appearance", "Second suppression hearing. Judge Reese granted motion \u2014 breathalyzer result SUPPRESSED. State\u2019s .18 BAC evidence excluded. ADA Mehta visibly surprised. Outstanding: SFST ruling reserved (less critical now). Case posture dramatically improved."),
    E("2026-02-25", 0.3, "Phone/Email",      "Called client to report breathalyzer suppression. Client extremely relieved. Explained that without .18 BAC, felony aggravated DUI element collapses \u2014 State will likely offer misdemeanor plea. Advised client to stay compliant with bond conditions."),
    E("2026-02-27", 0.5, "Negotiation",      "Plea negotiation call with ADA Mehta. Proposed: plea to misdemeanor DUI (first offense treated), 11/29 suspended, $350 fine + court costs, unsupervised probation, DUI school. Mehta said she\u2019d consult with supervisor."),
    E("2026-03-01", 0.3, "Negotiation",      "ADA Mehta confirmed: State agrees to misdemeanor DUI plea, 11 months 29 days suspended, $350 fine + $350 court costs, 48 hrs community service, DUI school. Prior conviction waived as aggravator given suppressed BAC. Strong outcome."),
    E("2026-03-01", 0.3, "Phone/Email",      "Presented plea offer to client. Discussed terms: no jail time, license reinstated after DUI school and ignition interlock compliance, record eligible for expungement after probation. Client accepted. Scheduled plea hearing 3/3."),
    E("2026-03-03", 0.5, "Drafting",         "Drafted plea paperwork: Waiver of Rights, Plea Agreement, Agreed Order of Judgment. Reviewed with client by phone \u2014 client prep for court demeanor and judge\u2019s questions."),
    E("2026-03-03", 1.0, "Court Appearance", "Plea hearing before Judge Calvin Reese. Client entered Alford-flavored guilty plea to misdemeanor DUI. Sentence: 11/29 suspended, $350 fine + costs, DUI school, 48 hrs community service, 1-yr ignition interlock. Case No. 2026-CR-44821 CLOSED. Excellent result."),
]

HOLLISTER_MESSAGES = [
    M("client",   "2026-01-10 21:15", "I just got home from the jail. I\u2019m scared. My boss doesn\u2019t know and I have to be at work Monday. Is this really a felony?"),
    M("attorney", "2026-01-10 22:00", "Raymond, I understand how frightening this is. Yes, with your prior DUI and the refusal, you\u2019re charged as a felony right now. But I\u2019ve already spotted two issues: the officer\u2019s certification and the breathalyzer timing. We have real options here. We\u2019ll talk through everything at our meeting tomorrow morning. Get some rest \u2014 you did the right thing by calling us."),
    M("client",   "2026-01-12 09:30", "Will I lose my license? I drive 45 minutes each way to work and there\u2019s no bus where I live."),
    M("attorney", "2026-01-12 10:15", "I\u2019ve already filed a timely request for an administrative hearing with the DMV to contest the automatic 1-year revocation. That buys us time. Even if we can\u2019t stop the suspension entirely, there\u2019s a restricted license for work travel. Focus on the court case for now \u2014 that\u2019s where we can do the most damage to the State\u2019s case."),
    M("client",   "2026-01-28 18:00", "Any news from discovery? My last lawyer never told me anything."),
    M("attorney", "2026-01-28 19:00", "Good news today \u2014 I found something important in discovery. The officer who administered your field sobriety tests had an expired certification at the time of your arrest. Under Tennessee case law, that\u2019s a serious problem for the State. I\u2019m filing a suppression motion this week. Also pulling the breathalyzer calibration records. Don\u2019t say anything to anyone about the case \u2014 not friends, family, or social media."),
    M("client",   "2026-02-14 17:30", "How did the hearing go today? I was so nervous at work I couldn\u2019t concentrate."),
    M("attorney", "2026-02-14 18:30", "Good progress today. Judge Reese reserved his ruling on the field sobriety tests, which is common \u2014 he wants briefs on the breathalyzer issue I raised. Here\u2019s the key: I found that the breathalyzer used on you had not been calibrated within the required 45-day window. If Judge Reese suppresses that .18 BAC reading, the felony aggravated element essentially disappears. I have a supplemental filing ready. We\u2019re in a strong position."),
    M("client",   "2026-02-25 10:00", "My wife told me to call you. She said something happened in court? She saw you outside?"),
    M("attorney", "2026-02-25 10:30", "Raymond \u2014 great news I was just about to call you. Judge Reese suppressed your breathalyzer result. The .18 BAC is gone from the evidence. Without it, the State can\u2019t prove the aggravated DUI element that makes it a felony. I\u2019m opening plea negotiations with ADA Mehta today. I expect a misdemeanor offer shortly. This is exactly the outcome we were working toward."),
    M("client",   "2026-03-01 14:00", "You said they agreed to the misdemeanor? I can\u2019t believe this. What happens now? Do I have to go back to court?"),
    M("attorney", "2026-03-01 15:00", "Yes \u2014 misdemeanor DUI, 11 months 29 days all suspended, $350 fine, DUI school, 48 hours community service, ignition interlock for one year. No jail time. Plea hearing is scheduled for March 3rd \u2014 this Monday. I\u2019ll have you in and out of the courthouse in under an hour. After you complete probation, this conviction can be expunged from your record. You did everything right throughout this process. See you Monday."),
]

HOLLISTER_PAYMENTS = [
    P(3500.00, "credit_card", "2026-01-10", "$3,500 retainer \u2014 criminal defense representation"),
    P(1750.00, "check",       "2026-03-03", "$1,750 final balance \u2014 case closed, misdemeanor DUI plea"),
]


# ─────────────────────────────────────────────────────────────────────────────
# CASE 2: Linda M. Chen — Employment Law — SophiaH
# Davidson Co. Circuit Court Case No. 26C1140
# Outcome: Mediation ordered; strong settlement position ($75k+ target)
# ─────────────────────────────────────────────────────────────────────────────

CHEN_BILLING = [
    E("2026-01-15", 0,   "Intake",                "INTAKE \u2014 Employment Law.\nMatter: Wrongful termination and hostile work environment based on age (54) and gender at NovaTech Solutions, LLC. Client terminated Jan 6, 2026 after 11 years. Replaced by 29-year-old male. Assigned to Sophia L. Hargrove, Esq."),
    E("2026-01-15", 1.0, "Meeting",               "Initial consultation \u2014 reviewed termination letter, performance reviews (all \u2018Exceeds Expectations\u2019 through 2024), and client\u2019s documented complaints to HR (Aug and Nov 2025). Confirmed strong McDonnell Douglas prima facie case: protected class, qualified, adverse action, replaced by younger male. Engaged on contingency + retainer."),
    E("2026-01-17", 1.5, "Research",              "Research: McDonnell Douglas Corp. v. Green, 411 U.S. 792 (1973) \u2014 burden-shifting framework applies in THRA context. THRA \u00a7 4-21-401 et seq. \u2014 age+gender protected class. Reviewed EEOC Enforcement Guidance on sex discrimination. Identified comparator: Brad Kowalski, 29 (Linda\u2019s replacement). Also studied NovaTech\u2019s RIF policy \u2014 never applied to Linda\u2019s role before."),
    E("2026-01-20", 0.5, "Filing",                "Filed EEOC Charge of Discrimination (Charge No. 494-2026-00841) for age and sex discrimination. Simultaneously filed THRA administrative complaint with Tennessee Human Rights Commission. Both required before litigation. Right-to-sue expected in 180 days, but will request early issuance."),
    E("2026-01-22", 0.5, "Phone/Email",           "Call with client re: evidence preservation. Advised: save all work emails to personal device, preserve performance reviews, keep notes of any contact from NovaTech. Client reported HR Director David Park called her at home \u2014 warned her not to \u201cmake this difficult.\u201d Documented. Do not engage further with NovaTech."),
    E("2026-01-28", 2.0, "Witness/Investigation", "Witness interviews \u2014 3 former NovaTech colleagues (conducted by phone, signed declarations obtained): (1) Marcus Webb, 61, also terminated in Jan RIF \u2014 replaced by 26-yr-old; (2) Janet Flores, 47, still employed, witnessed supervisor Rob Coleman\u2019s hostile comments about \u201cold guard\u201d employees; (3) Paul Stein, 52, corroborated pattern of younger replacements. Key declarations secured."),
    E("2026-02-01", 1.0, "Drafting",              "Drafted demand letter to NovaTech CEO and legal counsel (Whitmore & Associates, atty: Greg Stanton). Demand: $125,000 (back pay $38k + front pay $42k + emotional distress $45k). Attached: performance reviews, EEOC charge confirmation, witness declaration summary. 21-day response window."),
    E("2026-02-10", 0.3, "Phone/Email",           "Received denial letter from Greg Stanton, Whitmore & Associates, dated Feb 9. Denial cites: \u201clegitimate business restructuring,\u201d \u201cperformance concerns not reflected in formal reviews,\u201d and \u201cno evidence of discriminatory animus.\u201d Boilerplate denial. Expected. Will proceed to litigation."),
    E("2026-02-12", 1.5, "Drafting",              "Drafted Complaint in Davidson County Circuit Court. Counts: (1) Sex Discrimination \u2014 THRA \u00a7 4-21-401; (2) Age Discrimination \u2014 THRA \u00a7 4-21-401; (3) Hostile Work Environment \u2014 THRA; (4) Retaliation (re: HR Director\u2019s call). Included all required THRA exhaustion allegations."),
    E("2026-02-12", 0.3, "Filing",                "Filed complaint in Davidson County Circuit Court. Case No. 26C1140. Assigned to Hon. Marianne Okafor, Division VI. Summons issued to NovaTech Solutions, LLC and served Feb 15 via process server. 30-day answer deadline."),
    E("2026-02-18", 0.5, "Research",              "Research on Judge Okafor\u2019s employment discrimination rulings: 3 prior THRA cases \u2014 2 plaintiff verdicts, 1 defense. Known for rigorous discovery management and strong summary judgment scrutiny on pretext. Will push for full discovery before any MSJ. Good venue for plaintiff."),
    E("2026-02-20", 0.5, "Phone/Email",           "Email exchange with Stanton re: discovery schedule. NovaTech answered complaint Feb 19 with general denial. Stanton proposed 90-day discovery window with 30-day document production. Countered for 60-day document production. Agreed on Feb 25 scheduling conference with Judge Okafor."),
    E("2026-02-25", 3.0, "Witness/Investigation", "Deposition of NovaTech HR Director David Park (7 hrs). Key admissions: (1) Park confirmed no written performance improvement plan was ever issued to client; (2) admitted \u201cmanagement wanted fresh energy in the department\u201d \u2014 code language; (3) confirmed client\u2019s replacement (Brad Kowalski) had 3 years experience vs. client\u2019s 11 years; (4) could not identify specific \u2018performance concerns\u2019 other than vague \u2018cultural fit.\u2019 Excellent deposition \u2014 pretext well-established."),
    E("2026-03-01", 1.0, "Research",              "Retained Dr. Susan Park, Ph.D. (HR expert, Vanderbilt) as expert witness. Dr. Park specializes in discriminatory RIF analysis. Reviewed NovaTech\u2019s RIF data: of 7 employees terminated, 5 were over 50. Industry standard RIF should yield ~30% in that age band. NovaTech\u2019s was 71%. Expert will testify to statistical pattern of age-based selection."),
    E("2026-03-01", 0.5, "Drafting",              "Drafted and filed expert witness disclosure per TRCP 26.02(4): Dr. Susan Park, expected to testify on discriminatory statistical patterns in NovaTech\u2019s RIF. Filed with Davidson Circuit Ct. and served on Stanton. Stanton has 14 days to depose or object."),
    E("2026-03-03", 0.5, "Travel",                "Travel to Davidson County Circuit Court for scheduling conference (50-min round trip). Parking + mileage logged."),
    E("2026-03-03", 1.5, "Court Appearance",      "Scheduling conference before Judge Okafor. Court ordered: 90-day discovery cutoff (June 1), mediation required before trial setting. Mediator to be agreed upon within 30 days. Trial not before Q4 2026. Judge noted Park deposition admissions as \u201csignificant\u201d \u2014 favorable signal. Stanton appeared visibly concerned."),
    E("2026-03-03", 0.5, "Negotiation",           "Post-hearing call with Stanton. He asked if client would consider settlement \u201cbefore things get expensive.\u201d Indicated NovaTech is \u201copen to resolution.\u201d Told him we\u2019d need a number north of $75,000 to consider mediation productive. He said he\u2019d talk to client. This is progress."),
]

CHEN_MESSAGES = [
    M("client",   "2026-01-15 15:00", "I still can\u2019t believe this happened. I gave NovaTech 11 years. Perfect reviews every year. And then one day they just \u2018restructure\u2019 me out? And now Brad \u2014 who I trained \u2014 has my job. I\u2019m 54. Who\u2019s going to hire me?"),
    M("attorney", "2026-01-15 16:30", "Linda, what happened to you is wrong and potentially illegal. The facts you\u2019ve described \u2014 consistent high performance, 11 years of service, replaced by someone significantly younger and less experienced, after documented complaints to HR \u2014 are exactly the pattern employment discrimination law is designed to address. We have a strong case. I\u2019ve already started the administrative filing process. I\u2019m going to fight hard for you."),
    M("client",   "2026-01-22 11:00", "NovaTech keeps sending me forms about COBRA and they want me to sign a severance agreement. It has a clause that says I give up the right to sue. Should I sign?"),
    M("attorney", "2026-01-22 11:45", "Do NOT sign anything from NovaTech without showing it to me first. That severance agreement almost certainly contains a release of all legal claims \u2014 signing it would waive your right to pursue this case. Also: do not respond to the HR Director\u2019s calls. Any contact from NovaTech should come through me. I\u2019ve already filed your EEOC charge \u2014 they\u2019ll receive formal notice this week."),
    M("client",   "2026-02-01 09:00", "Did you send the demand letter? What happens if they say no?"),
    M("attorney", "2026-02-01 09:45", "Yes, the demand letter went out yesterday to NovaTech\u2019s attorneys, Whitmore & Associates. We\u2019re demanding $125,000. If they say no \u2014 and they probably will at first \u2014 we file suit in Davidson County Circuit Court. The lawsuit is already drafted and ready to go. Filing will force them to spend money on defense, and once they see the deposition I\u2019m going to take of their HR Director, settlement becomes more attractive."),
    M("client",   "2026-02-25 19:00", "I\u2019ve been nervous all day. How did the deposition go?"),
    M("attorney", "2026-02-25 20:00", "Today was excellent. Their HR Director, David Park, testified for 7 hours and made several admissions that are very helpful to our case. He confirmed there was never a written performance improvement plan, couldn\u2019t point to specific performance problems, and used language like \u2018fresh energy\u2019 to describe why they let you go. Our expert witness Dr. Susan Park is also going to testify about the statistical pattern of NovaTech targeting older employees in this layoff. We are in a very strong position."),
    M("client",   "2026-03-03 17:00", "I heard from a former coworker that NovaTech is really worried about this case. Is that true?"),
    M("attorney", "2026-03-03 18:00", "I can confirm that after today\u2019s court hearing, opposing counsel called me and asked if you\u2019d be open to settlement discussions. Judge Okafor ordered mediation \u2014 that\u2019s standard \u2014 but their tone has shifted significantly. I told him we\u2019d need a number over $75,000 to have a productive conversation. I believe we can do better than that at mediation, especially with Dr. Park\u2019s statistical report and the admissions from the HR Director\u2019s deposition. You\u2019ve been incredibly patient through this. We\u2019re close."),
]

CHEN_PAYMENTS = [
    P(5000.00, "credit_card", "2026-01-15", "$5,000 retainer \u2014 employment discrimination representation"),
    P(8750.00, "check",       "2026-03-03", "$8,750 contingency partial \u2014 case in active litigation, mediation pending"),
]


# ─────────────────────────────────────────────────────────────────────────────
# BobbyT Enrichment — Criminal Defense (Endocide)
# DUI charges resolve to reckless driving plea
# ─────────────────────────────────────────────────────────────────────────────

BOBBYT_EXTRA_BILLING = [
    E("2026-02-05", 0.5, "Research",         "Reviewed arrest report in detail. Officer Cmdr. Jensen\u2019s notes indicate client immediately requested an attorney upon first contact. Under Miranda v. Arizona and State v. Sawyer, all statements made after that request must be suppressed. Filed initial suppression memo."),
    E("2026-02-07", 0.3, "Phone/Email",      "Called client to confirm: he asked for an attorney \u201cat least 3 times\u201d before Jensen read Miranda rights. Client clear and consistent on this. Will be key testimony. Advised client not to discuss with anyone."),
    E("2026-02-10", 0.5, "Filing",           "Filed Motion to Suppress all client statements post-arrest, citing violation of Miranda right to counsel. Tennessee v. Sawyer, 156 S.W.3d 910 (Tenn. Ct. App. 2004). Hearing set for March 5 before General Sessions Judge Hartley."),
    E("2026-02-14", 0.5, "Drafting",         "Drafted letter to ADA Briggs (Davidson DA\u2019s office) previewing suppression motion and requesting early plea discussion. Noted client\u2019s cooperation and employment record \u2014 no prior felonies. Proposed: reduce to reckless driving in exchange for early resolution."),
    E("2026-02-20", 0.3, "Phone/Email",      "Call with ADA Briggs: she is interested in plea. Noted Officer Jensen has a prior citizen complaint for Miranda violation (2024, unrelated case). Said she\u2019d consult with supervisor about reckless driving offer. Favorable sign."),
    E("2026-03-02", 1.5, "Court Appearance", "Arraignment before Judge Hartley. Client entered not guilty plea. Briggs did not oppose reasonable bond modification. Next date: March 19 suppression hearing. Jensen was present \u2014 made eye contact, seemed uncomfortable when I referenced the 2024 complaint in sidebar with Briggs."),
    E("2026-03-05", 0.5, "Negotiation",      "ADA Briggs called with plea offer: plead to reckless driving (Class B misdemeanor), $250 fine + court costs, no jail, no DUI record. License unaffected. Discussed with client in principle \u2014 client open to it. Pending formal written offer."),
    E("2026-03-07", 0.3, "Phone/Email",      "Called client with full plea terms. Reckless driving, $250 fine, 6 months unsupervised probation, attend driver improvement class. No DUI conviction, no DUI school, license intact. Client relieved \u2014 accepted. Scheduled plea hearing March 15."),
    E("2026-03-10", 0.5, "Drafting",         "Drafted plea paperwork: Agreed Plea, Waiver of Rights, Order of Disposition. Reviewed by phone with client. Explained: reckless driving is not DUI; no mandatory license suspension; eligible for expungement after probation. Client understood and signed."),
    E("2026-03-15", 1.0, "Court Appearance", "Plea hearing before Judge Hartley. Client pled guilty to Reckless Driving. Sentence: $250 fine + $212 court costs, 6 months unsupervised probation, driver improvement class. DUI charges dismissed with prejudice. Case No. 2026-CR-00123 CLOSED. Great result for client."),
    E("2026-03-15", 0.3, "Filing",           "Filed Order of Disposition with clerk. Confirmed copy of agreed judgment to client by email. Provided expungement timeline: eligible after successful probation completion. Client expressed gratitude."),
    E("2026-03-10", 0,   "Overhead",         "Administrative: updated case file, archived discovery documents, closed matter."),
]

BOBBYT_EXTRA_MESSAGES = [
    M("client",   "2026-02-05 20:00", "I\u2019ve been stressed about this. My boss found out somehow. Will this affect my job?"),
    M("attorney", "2026-02-05 20:45", "Bobby, I found something important in your arrest report today. The officer\u2019s own notes show that you asked for an attorney before they read you your rights. Under Miranda, anything you said after that point cannot be used against you. I\u2019m filing a suppression motion this week. Your job situation depends on the outcome of the case \u2014 let\u2019s focus on getting the charges reduced or dropped."),
    M("client",   "2026-02-07 18:00", "Yes I definitely asked multiple times. I kept saying \u2018I want a lawyer\u2019 and he just kept asking questions anyway."),
    M("attorney", "2026-02-07 18:30", "That\u2019s exactly what I needed to hear. Stay consistent on that \u2014 you\u2019ll likely be asked about it again. Don\u2019t discuss the details with family or friends. I\u2019ll have the suppression motion filed by end of week. I also found that this officer had a prior complaint for the same thing in 2024 \u2014 that\u2019s very useful."),
    M("client",   "2026-03-05 17:30", "The DA offered something? What is it?"),
    M("attorney", "2026-03-05 18:00", "Good news \u2014 the DA offered reckless driving in exchange for dropping the DUI. That means no DUI on your record, no DUI school, your license stays intact, and you\u2019re just looking at a $250 fine and six months probation. This is a very favorable outcome. I\u2019ll send you the full terms in writing. Let me know if you want to accept and we\u2019ll schedule the plea hearing."),
    M("client",   "2026-03-07 10:00", "Yes I want to accept. I can\u2019t believe this might actually be over. Thank you so much."),
    M("attorney", "2026-03-15 14:00", "Bobby \u2014 we\u2019re done. Reckless driving conviction entered, DUI dismissed. You have six months of easy probation, a driver improvement class, and then you can apply to have this expunged entirely. You handled this whole process well. Take care of yourself."),
]

BOBBYT_EXTRA_PAYMENTS = [
    P(1050.00, "credit_card", "2026-03-10", "$1,050 balance payment \u2014 case resolved, reckless driving plea"),
]


# ─────────────────────────────────────────────────────────────────────────────
# DerekW Enrichment — Personal Injury (SophiaH)
# Rear-end collision, L4-L5 herniation; State Farm settles $61,500
# ─────────────────────────────────────────────────────────────────────────────

DEREKW_EXTRA_BILLING = [
    E("2026-03-05", 1.0, "Research",              "Rear-end liability research: Tennessee follows modified comparative fault (TCA \u00a7 29-11-103). At-fault driver cited at scene \u2014 0% fault for client. Reviewed MRI report: L4-L5 disc herniation confirmed, radiologist notes nerve compression. Prognosis: 12-18 months PT, possible surgical consult. Case value significantly increased from initial estimate."),
    E("2026-03-07", 0.3, "Phone/Email",           "Call with client: confirmed medical bills to date ($21,200), lost wages (8 wks x $1,150/wk = $9,200), property damage ($4,200 vehicle). Client still in PT twice weekly. Advised: do not settle medical liens yet, keep documenting every missed work day. State Farm has been calling him directly \u2014 instructed client to direct all calls to our office."),
    E("2026-03-10", 0.3, "Filing",                "Filed notice of representation with State Farm Insurance. Directed all future communications to our office. Requested complete claim file and adjuster notes. State Farm adjuster is Michael Houser (615-330-4400 ext. 812)."),
    E("2026-03-14", 1.0, "Drafting",              "Drafted demand package to State Farm: $84,600 total demand (medical specials $21,200 + lost wages $9,200 + property damage $4,200 + pain and suffering $50,000). Included: MRI report, medical billing summary, employer wage verification letter, police report with at-fault citation. Sent certified mail."),
    E("2026-03-21", 0.3, "Phone/Email",           "State Farm adjuster Houser called: acknowledged receipt of demand, invoked 21-day review period per Tenn. statute. Expected. Will follow up March 31. Client is frustrated with the delay \u2014 explained this is normal and we should not accept lowball offers."),
    E("2026-03-24", 1.5, "Witness/Investigation", "Retained Robert Dyer, P.E. (accident reconstruction expert, Dyer Forensics LLC) to analyze impact data. Dyer has testified in 40+ Davidson/Blount/Rutherford County cases. Reviewed police report skid marks, vehicle damage photos, and dashcam still frames. Preliminary finding: at-fault vehicle was traveling ~35 mph at impact into a stopped vehicle \u2014 consistent with severe disc injury mechanism."),
    E("2026-03-31", 0.3, "Phone/Email",           "State Farm issued property damage check: $4,200. Forwarded to client. Confirmed medical and wage claim remains open. Houser said they\u2019re \u201creview[ing] the medical documentation carefully\u201d \u2014 standard delay. Dyer report expected April 7."),
    E("2026-04-07", 0.5, "Negotiation",           "State Farm\u2019s initial liability offer: $28,000. Rejected. Countered at $72,000 (net of property damage already paid). Houser said he\u2019d escalate to regional supervisor. Also filed litigation hold notice with State Farm legal department referencing potential bad-faith delay if case goes to verdict above policy limits."),
    E("2026-04-10", 0.3, "Phone/Email",           "Received Dyer\u2019s written report: confirms 34-37 mph impact into stationary vehicle. Report includes vehicle dynamics analysis and biomechanical causation opinion re: L4-L5 injury. This eliminates any comparative fault argument for State Farm. Forwarded report to Houser with cover letter."),
    E("2026-04-14", 0.5, "Negotiation",           "State Farm escalated to $52,000. Filed litigation hold notice and informed Houser client has retained accident reconstruction expert. Countered at $67,000. Houser said he\u2019d have a \u201cfinal answer by Friday.\u201d Discussed with client: $61,500 would be acceptable floor; $67k is the target."),
    E("2026-04-17", 0.3, "Phone/Email",           "Houser called with \u201cfinal offer\u201d: $61,500. Presented to client same day. Breakdown: medical specials $21,200 + lost wages $9,200 + pain/suffering $31,100. Client accepted. Instructed Houser to prepare release documents and settlement check."),
    E("2026-04-20", 0,   "Overhead",              "Administrative: case file closed, settlement documents signed and filed, lien resolution confirmed with client\u2019s medical providers. Final disbursement: $61,500 gross \u2014 33% contingency fee = $20,295. Client net: $41,205 (plus $4,200 property already paid)."),
]

DEREKW_EXTRA_MESSAGES = [
    M("client",   "2026-03-05 19:00", "I\u2019ve been going to PT three times a week and my back is still killing me. The bills are piling up. When is this going to move?"),
    M("attorney", "2026-03-05 19:45", "Derek, I hear you \u2014 and I want you to know: your medical expenses and ongoing treatment are exactly what builds the value of your claim. Every bill, every PT appointment, every day you can\u2019t work is documented damages. The MRI confirms the injury. I\u2019m preparing the demand to State Farm this week with a full damages package. Do NOT talk to State Farm directly \u2014 all calls go through our office from now on."),
    M("client",   "2026-03-21 10:00", "State Farm called my cell phone again even though I told them to call you. They said my case is \u2018under review.\u2019 What does that mean?"),
    M("attorney", "2026-03-21 10:30", "That is completely normal delay tactic. I\u2019ve already sent them a representation letter \u2014 if they contact you directly again, that is a potential ethics violation on their part. Give them my number and hang up. Their \u201cunder review\u201d language just means they\u2019re trying to minimize the payout. We sent a $84,600 demand. Their first offer will be insultingly low \u2014 don\u2019t panic when it is. That\u2019s expected."),
    M("client",   "2026-04-07 16:00", "They offered $28,000. After everything I\u2019ve been through? That\u2019s not even close to covering my medical bills."),
    M("attorney", "2026-04-07 17:00", "I\u2019ve already rejected it and countered at $72,000. The $28k offer is a formality \u2014 they\u2019re required to make an offer. I also just received the accident reconstruction expert\u2019s report: he confirms the other driver was doing 35 mph into your stationary car. That eliminates any argument that you share fault. I forwarded it to State Farm today. This changes the negotiation significantly."),
    M("client",   "2026-04-14 11:00", "What\u2019s happening? Have they come up at all?"),
    M("attorney", "2026-04-14 11:45", "Yes \u2014 they\u2019ve moved to $52,000. We\u2019re negotiating. I\u2019ve countered at $67,000 and told them we\u2019re prepared to file suit and let a Blount County jury decide. Our expert report is a strong piece of evidence. I expect we can get this above $60,000. I\u2019ll be in touch as soon as I hear back from their supervisor."),
    M("client",   "2026-04-17 15:30", "You said $61,500? Is that a good result? I feel like I should hold out for more."),
    M("attorney", "2026-04-17 16:15", "Derek, $61,500 is a very good result for this case. Your documented specials were $30,400 (medical + wages). State Farm paid $4,200 for property already. This gets you an additional $31,100 for pain and suffering \u2014 which is more than 100% of your specials, which is well above average for a case like this without going to trial. Going to trial adds 12-18 months and risk. I recommend you take this. Your net after our 33% fee will be $41,205, plus the $4,200 property check already in your pocket. Let me know and I\u2019ll get the release drafted today."),
]

DEREKW_EXTRA_PAYMENTS = [
    P(20295.00, "check", "2026-04-20", "33% contingency fee on $61,500 settlement \u2014 case closed"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Seeding functions
# ─────────────────────────────────────────────────────────────────────────────

def seed_new_client(username, data):
    if not FORCE:
        existing = app.load_client(username)
        if existing and existing.get("seeded"):
            print(f"  [SKIP] {username} already seeded (use --force to re-seed)")
            return
    data["seeded"] = True
    data["hours_billed"] = hours_from_log(data.get("billing_log", []))
    app.save_client(data)
    print(
        f"  [OK] Created {username}: {data['client_name']} \u2014 "
        f"{len(data['billing_log'])} log entries, "
        f"{len(data['messages'])} messages, "
        f"${data.get('hours_paid', 0) * app.HOURLY_RATE:,.2f} collected"
    )


def enrich_existing_client(username, extra_billing, extra_messages, extra_payments):
    c = app.load_client(username)
    if not c:
        print(f"  [WARN] {username} not found \u2014 skipping")
        return
    if not FORCE and c.get("enriched"):
        print(f"  [SKIP] {username} already enriched (use --force to re-enrich)")
        return
    c.setdefault("billing_log", []).extend(extra_billing)
    c.setdefault("messages", []).extend(extra_messages)
    apply_payments(c, extra_payments)
    c["hours_billed"] = hours_from_log(c["billing_log"])
    c["enriched"] = True
    app.save_client(c)
    print(
        f"  [OK] Enriched {username}: "
        f"+{len(extra_billing)} entries, "
        f"+{len(extra_messages)} msgs, "
        f"+{len(extra_payments)} payments, "
        f"total hrs_billed={c['hours_billed']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== MT Legal Case Seeder ===")
    print(f"HOURLY_RATE = ${app.HOURLY_RATE:.0f}/hr")
    print(f"FORCE = {FORCE}\n")

    print("Creating new clients...")

    # ── RHollister ──
    hollister = {
        "username":            "RHollister",
        "password":            "password",
        "must_change_password": False,
        "client_name":         "Raymond T. Hollister",
        "full_name":           "Raymond T. Hollister",
        "case_type":           "Criminal Defense",
        "assigned_attorney":   "Endocide",
        "legal_issue":         "Felony DUI with refusal (.18 BAC, prior DUI 6 yrs ago), Davidson Co. Cr. Case No. 2026-CR-44821. Breathalyzer suppressed (45-day calibration violation). Plea entered to misdemeanor DUI, 11/29 suspended, $350 fine, DUI school. Case CLOSED.",
        "legal_issue_summary": "DUI felony reduced to misdemeanor after breathalyzer evidence suppressed. Case closed.",
        "next_court_date":     "",
        "phone":               "(615) 555-0247",
        "email":               "rhollister@gmail.com",
        "google_drive_url":    "",
        "next_meeting":        "",
        "client_folder":       str(app.CLIENT_FILES_DIR / "RHollister"),
        "billing_log":         list(HOLLISTER_BILLING),
        "time_logs":           [],
        "notes":               [],
        "messages":            list(HOLLISTER_MESSAGES),
        "hours_paid":          0,
        "payments":            [],
        "case_no":             "2026-CR-44821",
        "charges":             "DUI \u2014 T.C.A. \u00a7 55-10-401 (Aggravated/Felony); DUI with Refusal \u2014 T.C.A. \u00a7 55-10-406",
        "charge_level":        "Felony (Class E) \u2014 resolved to Misdemeanor",
        "county":              "Davidson",
        "court":               "Davidson County Criminal Court \u2014 Division IV",
        "activity_log":        [],
        "case_number":         "EL-SEED-001",
        "archived":            False,
    }
    apply_payments(hollister, HOLLISTER_PAYMENTS)
    seed_new_client("RHollister", hollister)

    # ── LChen ──
    chen = {
        "username":            "LChen",
        "password":            "password",
        "must_change_password": False,
        "client_name":         "Linda M. Chen",
        "full_name":           "Linda M. Chen",
        "case_type":           "Employment Law",
        "assigned_attorney":   "SophiaH",
        "legal_issue":         "Wrongful termination and hostile work environment based on age (54) and gender at NovaTech Solutions, LLC. Replaced by 29-yr-old male after 11 years of exemplary service. Davidson Co. Circuit Court Case No. 26C1140, assigned to Hon. Marianne Okafor. Mediation ordered. Strong settlement position \u2014 target $75,000+.",
        "legal_issue_summary": "Age and gender discrimination claim against NovaTech Solutions. Mediation ordered by court after strong deposition of HR Director.",
        "next_court_date":     "",
        "phone":               "(615) 555-0388",
        "email":               "linda.chen@email.com",
        "google_drive_url":    "",
        "next_meeting":        "",
        "client_folder":       str(app.CLIENT_FILES_DIR / "LChen"),
        "billing_log":         list(CHEN_BILLING),
        "time_logs":           [],
        "notes":               [],
        "messages":            list(CHEN_MESSAGES),
        "hours_paid":          0,
        "payments":            [],
        "case_no":             "26C1140",
        "charges":             "THRA \u00a7 4-21-401 Sex Discrimination; THRA \u00a7 4-21-401 Age Discrimination; THRA Hostile Work Environment; THRA Retaliation",
        "charge_level":        "",
        "county":              "Davidson",
        "court":               "Davidson County Circuit Court \u2014 Division VI",
        "activity_log":        [],
        "case_number":         "EL-SEED-002",
        "archived":            False,
    }
    apply_payments(chen, CHEN_PAYMENTS)
    seed_new_client("LChen", chen)

    print("\nEnriching existing clients...")
    enrich_existing_client("BobbyT", BOBBYT_EXTRA_BILLING,  BOBBYT_EXTRA_MESSAGES,  BOBBYT_EXTRA_PAYMENTS)
    enrich_existing_client("DerekW", DEREKW_EXTRA_BILLING,  DEREKW_EXTRA_MESSAGES,  DEREKW_EXTRA_PAYMENTS)

    print("\nDone. Run verification:")
    print("  python -c \"import app; [print(u, '|', app.load_client(u).get('hours_billed'), 'hrs') for u in ['RHollister','LChen','BobbyT','DerekW']]\"")
