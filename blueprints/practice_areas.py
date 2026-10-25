"""blueprints/practice_areas.py — Marketing copy for the practice-area pages.

case_types are the real intake dropdown values (see CASE_ATTORNEY_MAP and
templates/intake.html) — the first one pre-selects the intake form's Case Type
field when a visitor clicks through. MT Legal is a solo practice, so every area
is handled by the managing partner.

Optional sections, rendered by templates/practice_area.html only when present:
  overview   — a paragraph under the page head
  local      — how the matter plays out in Nashville / Middle Tennessee courts
  structures — cards: {name, summary, fits}
  process    — ordered steps: {title, detail}
  fees       — rows: {tier, fee}, with fees_note underneath
  faqs       — {q, a}

Every area also has helps: plain-language points on how representation helps,
shown in the expandable homepage cards and on the practice page.
"""

PRACTICE_AREAS = {
    "ai-emerging-tech": {
        "name":       "AI & Emerging Technology",
        "tagline":    "Legal strategy for businesses and creators building with or deploying "
                      "artificial intelligence: contracts, IP, privacy, liability, and compliance.",
        "case_types": ["AI / Technology Law"],
        "helps": [
            "Negotiates AI vendor and licensing contracts so you keep rights to your data and outputs, and the vendor carries its share of the risk.",
            "Protects your work and identity, including voice and likeness rights under Tennessee's ELVIS Act.",
            "Writes AI use policies that keep confidential and customer data out of public AI tools.",
            "Represents you when a regulator, customer, or competitor challenges how your AI is built or used.",
        ],
        "overview":   "AI law is being written in real time: state statutes, federal agency "
                      "guidance, the EU AI Act for companies with European users, and a wave of "
                      "copyright and privacy litigation. Nashville sits at the center of one of "
                      "the first fights: Tennessee's ELVIS Act protects artists' voices from AI "
                      "cloning. We help companies, creators, and founders adopt AI without "
                      "inheriting its liability.",
        "focus": [
            "AI vendor, licensing, and SaaS contracts: data rights, indemnities, and output ownership",
            "Copyright and IP in AI-generated works and training data",
            "Voice and likeness rights under Tennessee's ELVIS Act, vital for Nashville's music industry",
            "Privacy and data protection under the Tennessee Information Protection Act",
            "AI use policies, governance programs, and risk assessments",
            "Liability for automated decisions in consumer protection, hiring, and discrimination",
            "AI agents and smart contracts that transact on-chain",
        ],
        "process": [
            {"title": "AI inventory",
             "detail": "Which tools you build, buy, or let employees use, and what data flows "
                       "into them."},
            {"title": "Risk map",
             "detail": "IP, privacy, contract, and regulatory exposure, ranked by what matters "
                       "most to your business."},
            {"title": "Contracts and policies",
             "detail": "Vendor terms renegotiated, customer terms updated, and an internal AI "
                       "policy employees can follow."},
            {"title": "Ongoing counsel",
             "detail": "Updates as new laws take effect and new tools are adopted."},
        ],
        "faqs": [
            {"q": "Who owns content my AI tool creates?",
             "a": "The U.S. Copyright Office requires human authorship, so purely AI-generated "
                  "material may not be protected. Between you and your vendor, the contract "
                  "decides, which is why the terms matter."},
            {"q": "What is the ELVIS Act?",
             "a": "A 2024 Tennessee law that adds a person's voice to the right of publicity "
                  "and creates liability for unauthorized AI voice and likeness cloning."},
            {"q": "Does my business need an AI policy?",
             "a": "If employees use generative AI with customer, client, or confidential data, "
                  "yes. A clear policy prevents the most common and costly mistakes."},
        ],
    },
    "criminal-defense": {
        "name":       "Criminal Defense",
        "tagline":    "DUI, drug, assault, theft, and felony defense in Davidson, Rutherford, "
                      "and surrounding county courts, from someone who knows how they work.",
        "case_types": ["Criminal Defense"],
        "helps": [
            'Protects your rights from the first police contact. No statements, searches, or interviews without counsel.',
            "Challenges the State's evidence: the stop, the search, lab results, and witness credibility.",
            'Negotiates with prosecutors for dismissal, diversion, or reduced charges.',
            "Takes your case to trial when the State can't prove it, and pursues expungement afterward.",
        ],
        "overview":   "Madison Biggs built his career on the defense side of the Davidson "
                      "County docket and, before law school, worked inside the Rutherford "
                      "County criminal court clerk's office. He knows how these cases move "
                      "from General Sessions arraignment through Criminal Court, and what it "
                      "takes to get a charge reduced, diverted, or dismissed.",
        "focus": [
            "Constitutional protections under the Fourth, Fifth, and Sixth Amendment challenges",
            "Suppression arguments and Brady/Giglio material",
            "Sentencing guidelines and mitigation",
            "Procedural defenses and challenges to the state’s case",
            "DUI defense, implied-consent hearings, and restricted licenses",
            "Judicial diversion, pretrial diversion, and expungement eligibility",
        ],
        "local": "Most Nashville cases begin in Davidson County General Sessions Court, where "
                 "bond, preliminary hearings, and many misdemeanor resolutions happen. Felonies "
                 "bound over go to the grand jury and Davidson County Criminal Court. We also "
                 "appear in Rutherford, Williamson, Wilson, and Sumner County courts.",
        "process": [
            {"title": "Call early",
             "detail": "Ideally before your first court date. Bond, no-contact conditions, and "
                       "evidence preservation can be addressed right away."},
            {"title": "Discovery and investigation",
             "detail": "Body-cam, dash-cam, lab results, and witness statements, reviewed for "
                       "suppression issues and weaknesses in the State's case."},
            {"title": "Negotiate or litigate",
             "detail": "Diversion, reduced charges, or dismissal where available. Trial when "
                       "it isn't."},
            {"title": "Clean up the record",
             "detail": "Expungement and record relief once the case is over, where Tennessee "
                       "law allows it."},
        ],
        "faqs": [
            {"q": "Should I talk to the police about my case?",
             "a": "Not without a lawyer. You can politely decline to answer questions and ask "
                  "for counsel. Anything you say can be used against you."},
            {"q": "Can my charge be expunged in Tennessee?",
             "a": "Often, yes. Dismissed charges, completed diversion, and many eligible "
                  "convictions can be expunged under T.C.A. § 40-32-101. Eligibility depends on "
                  "the offense and your record."},
            {"q": "What is judicial diversion?",
             "a": "A form of probation under T.C.A. § 40-35-313 that, if completed, ends in "
                  "dismissal and expungement. Not every charge or defendant qualifies."},
        ],
    },
    "civil-rights": {
        "name":       "Civil Rights Litigation",
        "tagline":    "Holding government accountable when it oversteps: police misconduct, "
                      "unlawful searches and arrests, and violations of your constitutional rights.",
        "case_types": ["Civil Rights", "Civil Litigation"],
        "helps": [
            "Evaluates whether your rights were violated and who can be held responsible, from individual officers to the agency itself.",
            "Preserves body-cam footage, records, and witness accounts before they disappear.",
            "Navigates qualified immunity and the Tennessee Governmental Tort Liability Act, which shape every claim against the government.",
            "Files suit in state or federal court and pursues compensation and changes in policy.",
        ],
        "overview":   "The same principle behind our criminal defense work drives our civil "
                      "rights practice: a person deserves protection from overreaching power. "
                      "When police, jails, or government agencies violate the Constitution, the "
                      "law gives you a way to hold them to account.",
        "focus": [
            "Excessive force and police misconduct claims under 42 U.S.C. § 1983",
            "False arrest, malicious prosecution, and unlawful search and seizure",
            "Jail and detention conditions, including denial of medical care",
            "First Amendment retaliation, including for recording or criticizing officials",
            "Due process and equal protection violations by state and local government",
            "Claims under the Tennessee Governmental Tort Liability Act",
        ],
        "local": "Civil rights claims against Metro Nashville and surrounding counties can be "
                 "filed in federal court for the Middle District of Tennessee or in state court. "
                 "In Tennessee, most § 1983 claims must be filed within one year, so acting "
                 "quickly matters.",
        "faqs": [
            {"q": "What is a § 1983 claim?",
             "a": "A federal lawsuit against people acting for the government, such as police "
                  "officers, who violate your constitutional rights."},
            {"q": "What is qualified immunity?",
             "a": "A defense that can shield officials from personal liability unless the right "
                  "they violated was clearly established. It is a hurdle, not always a bar."},
            {"q": "I have a criminal case pending. Can I still bring a civil rights claim?",
             "a": "Often, but the timing and what you say matter. The criminal case usually "
                  "comes first, and the two need to be handled together."},
        ],
    },
    "defi-digital-assets": {
        "name":       "DeFi & Digital Assets",
        "tagline":    "Token offerings, DAO and protocol entity structuring, and regulatory "
                      "posture for crypto-native businesses in Tennessee and beyond.",
        "case_types": ["DeFi / Crypto Law", "Crypto LLC Formation"],
        "helps": [
            'Puts a written securities analysis in place before you sell a single token. It is your best defense in an SEC or state inquiry.',
            "Chooses and forms the right entity so founders and DAO members aren't personally liable.",
            'Drafts token terms, governance documents, and disclosures that investors and exchanges expect.',
            'Represents you in regulatory inquiries, exchange disputes, and efforts to recover lost or stolen assets.',
            "Untangles crypto tax problems, from staking and yield income to missing cost basis, alongside your CPA.",
        ],
        "overview":   "Blockchain projects fail legally in predictable ways: an unregistered "
                      "securities offering, a DAO that turns out to be a general partnership "
                      "with unlimited liability, or a protocol that is accidentally a money "
                      "transmitter. We help founders, investors, and Nashville businesses choose "
                      "a structure on purpose and document it so it holds up.",
        "focus": [
            "Securities analysis under the Howey test, Reg D, Reg A+, Reg S, Reg CF",
            "Token standards and smart contract legal exposure",
            "DAO entity structuring (Wyoming DAO LLC, Cayman Foundation, and others)",
            "SEC, CFTC, FinCEN, and IRS regulatory posture",
            "Tennessee Securities Act notice filings and money-transmitter analysis",
            "Real-world-asset (RWA) tokenization, including real estate",
            "Yield from staking, lending, and liquidity pools: securities and tax treatment",
            "Crypto tax issues: cost basis, Form 1099-DA reporting, and IRS notices",
        ],
        "structures": [
            {"name": "Tennessee Decentralized Organization LLC",
             "summary": "Tennessee's DAO statute (T.C.A. Title 48, Chapter 250) lets an LLC be "
                        "governed by its members or by smart contract, with liability "
                        "protection for members.",
             "fits": "Tennessee-based DAOs and protocols that want a home-state entity."},
            {"name": "Wyoming DAO LLC / DUNA",
             "summary": "The longest-running US DAO frameworks. The DUNA (Decentralized "
                        "Unincorporated Nonprofit Association) suits large token-governed "
                        "communities without a central operator.",
             "fits": "Governance DAOs with many widely distributed token holders."},
            {"name": "Cayman Islands Foundation Company",
             "summary": "An ownerless foundation with directors and a supervisor; a common "
                        "wrapper for protocol treasuries and token issuers outside the US.",
             "fits": "Protocols with global users and a non-US token launch."},
            {"name": "Operating LLC + Token SPV",
             "summary": "A conventional development company paired with a separate special-"
                        "purpose vehicle that holds tokens, treasury, or IP, isolating liability.",
             "fits": "Venture-backed teams that need clean cap tables for investors."},
            {"name": "SAFE + Token Warrant / SAFT",
             "summary": "Early-stage financing that gives investors equity, future tokens, or "
                        "both, usually sold under Reg D to accredited investors.",
             "fits": "Pre-launch fundraising."},
            {"name": "Series LLC for pools and vaults",
             "summary": "Tennessee permits series LLCs (T.C.A. § 48-249-309), letting each pool, "
                        "vault, or asset sit in its own liability-segregated series.",
             "fits": "Funds, vault strategies, and multi-asset tokenization programs."},
        ],
        "process": [
            {"title": "Discovery call",
             "detail": "What the token does, who buys it, and where the team and users are."},
            {"title": "Regulatory map",
             "detail": "Securities, commodities, money transmission, sanctions, and tax "
                       "exposure, delivered as a written memo."},
            {"title": "Entity and documents",
             "detail": "Formation, operating agreement or charter, token terms, and governance "
                       "framework."},
            {"title": "Launch and ongoing compliance",
             "detail": "Form D and state notice filings, disclosures, and updates as the rules "
                       "change."},
        ],
        "faqs": [
            {"q": "Is my token a security?",
             "a": "Possibly. Under the Howey test the answer turns on how it is sold, what "
                  "buyers expect, and how decentralized the project really is. We analyze it "
                  "in writing before you sell."},
            {"q": "Do I need a DAO LLC?",
             "a": "A DAO with no legal wrapper risks being treated as a general partnership, "
                  "with members personally liable. A wrapper is usually worth it."},
            {"q": "How is staking or DeFi yield taxed?",
             "a": "The IRS treats staking rewards as ordinary income when you gain control of "
                  "them (Rev. Rul. 2023-14), and a later sale produces capital gain or loss. "
                  "Lending and liquidity-pool yield raise harder questions. Tennessee has no "
                  "state income tax on wages or investment income, but federal tax applies."},
            {"q": "What is Form 1099-DA?",
             "a": "A new IRS form brokers issue for crypto sales starting with 2025 "
                  "transactions, with cost-basis reporting phasing in after that. Gaps between "
                  "the form and your own records are a common source of IRS notices."},
            {"q": "Is a yield or staking program a security?",
             "a": "It can be. Programs where a platform pools customer assets and pays a "
                  "return have drawn securities enforcement. Structure and disclosures matter."},
            {"q": "Do you work with clients outside Tennessee?",
             "a": "Federal securities and commodities questions aren't limited by state. Where "
                  "another state's law governs, we coordinate with local counsel."},
        ],
    },
    "stablecoins": {
        "name":       "Stablecoins & Digital Payments",
        "tagline":    "Issue, accept, or build on stablecoins under the new federal framework, "
                      "and use them to grow: faster payments, lower fees, and global reach.",
        "case_types": ["Stablecoins / Digital Payments"],
        "helps": [
            "Maps where your business fits under the GENIUS Act and Tennessee money-transmitter rules before you launch.",
            "Drafts merchant, wallet, and platform terms so customers, partners, and processors know who carries the risk.",
            "Sets up treasury and accounting policies for holding stablecoins, including reserves, custody, and tax treatment.",
            "Represents you with banks, payment partners, and regulators as rules are finalized.",
        ],
        "overview":   "Stablecoins are digital dollars on a blockchain, and they are now one of "
                      "the fastest-growing payment rails in the world. The federal GENIUS Act "
                      "(2025) created the first national framework for payment stablecoins, with "
                      "reserve, disclosure, and licensing rules for issuers. For Nashville "
                      "businesses that means a real opportunity: settle payments in minutes "
                      "instead of days, cut card and wire fees, and reach customers abroad. We "
                      "help you capture that growth on a compliant footing.",
        "focus": [
            "GENIUS Act analysis for issuers, wallets, exchanges, and payment platforms",
            "Accepting stablecoin payments: merchant terms, refunds, chargebacks, and disclosures",
            "Corporate treasury: holding stablecoins, custody, and reserve policies",
            "Tennessee and multi-state money-transmitter licensing questions",
            "AML, KYC, and sanctions compliance for stablecoin flows",
            "Stablecoin yield and rewards programs, and when they raise securities issues",
            "Tax and accounting treatment of stablecoin receipts and payments",
        ],
        "structures": [
            {"name": "Merchant Acceptance Program",
             "summary": "Accept stablecoins through a payment processor that converts to dollars "
                        "or holds them, with customer terms covering pricing, refunds, and "
                        "disputes.",
             "fits": "Retailers, venues, and service businesses that want lower payment costs."},
            {"name": "Corporate Treasury Allocation",
             "summary": "A board-approved policy for holding part of operating cash in "
                        "stablecoins: approved coins, custody, limits, and reporting.",
             "fits": "Companies paying vendors or contractors abroad."},
            {"name": "Payment Platform or Wallet",
             "summary": "Software that lets users send, hold, or convert stablecoins. Licensing "
                        "turns on whether you ever control customer funds.",
             "fits": "Fintech startups and apps adding digital-dollar features."},
            {"name": "State-Qualified Issuer Path",
             "summary": "The GENIUS Act allows smaller issuers to operate under a state "
                        "regulatory regime that meets federal standards, instead of a federal "
                        "charter.",
             "fits": "Issuers planning a smaller, regional, or niche stablecoin."},
            {"name": "Cross-Border Payout Program",
             "summary": "Pay international contractors, creators, or suppliers in stablecoins, "
                        "with sanctions screening and local-law review built in.",
             "fits": "Businesses with global teams or royalty payees."},
            {"name": "Tokenized Settlement for Real Assets",
             "summary": "Use stablecoins as the payment leg for tokenized real estate or other "
                        "digital securities, so delivery and payment settle together.",
             "fits": "Tokenization sponsors and their investors."},
        ],
        "process": [
            {"title": "Use-case review",
             "detail": "Who sends, holds, and receives the stablecoin, and who touches customer "
                       "funds along the way."},
            {"title": "Regulatory map",
             "detail": "GENIUS Act status, money transmission, AML, sanctions, consumer "
                       "protection, and tax, in a written memo."},
            {"title": "Documents and partners",
             "detail": "Customer terms, processor and custodian agreements, and internal "
                       "policies."},
            {"title": "Launch and monitor",
             "detail": "Updates as federal and state regulators finalize their rules."},
        ],
        "faqs": [
            {"q": "What is the GENIUS Act?",
             "a": "A 2025 federal law creating the first national framework for payment "
                  "stablecoins. Issuers must be licensed, hold one-to-one reserves in cash and "
                  "short-term Treasuries, and publish reserve reports. Regulators are still "
                  "writing the implementing rules."},
            {"q": "Can my business accept stablecoins today?",
             "a": "Yes. Most merchants use a processor that converts to dollars or holds the "
                  "coins in custody. The legal work is in your customer terms, refund policy, "
                  "accounting, and choosing compliant partners."},
            {"q": "Can stablecoins pay interest?",
             "a": "The GENIUS Act bars issuers of payment stablecoins from paying interest or "
                  "yield to holders. Rewards offered by third parties raise their own "
                  "securities and consumer-protection questions."},
            {"q": "Are stablecoin payments taxable?",
             "a": "The IRS treats digital assets, including stablecoins, as property. Receiving "
                  "them as payment is income, and spending or converting them is a disposition "
                  "that must be reported, even when the gain is near zero."},
        ],
    },
    "real-estate-tokenization": {
        "name":       "Real Estate Tokenization",
        "tagline":    "Turn Nashville-area property into compliant digital securities: "
                      "fractional ownership, investor onboarding, and secondary transfers.",
        "case_types": ["Real Estate Tokenization", "Real Estate"],
        "helps": [
            'Structures the deal so investors buy compliant securities, not an accidental unregistered offering.',
            'Clears title, liens, and lender consent before the property moves into the owning entity.',
            'Drafts the offering documents and coordinates the auditor, transfer agent, and trading platform.',
            'Handles ongoing filings, investor communications, and resale compliance after launch.',
        ],
        "overview":   "Tokenization puts ownership interests in a property (or in the entity "
                      "that owns it) on a blockchain, so they can be issued, transferred, and "
                      "tracked as digital tokens. Done right, it opens a property to smaller "
                      "investors and faster transfers. Done wrong, it is an unregistered "
                      "securities offering. We handle the legal structure end to end.",
        "focus": [
            "Choosing the ownership vehicle: SPV LLC, series LLC, DST, or fund",
            "Securities exemptions: Reg D 506(b)/(c), Reg A+ Tier 1 and 2, Reg CF, Reg S",
            "Offering documents: PPM, operating agreement, subscription agreement, token terms",
            "Permissioned token standards (ERC-3643, ERC-1400) and transfer restrictions",
            "KYC/AML, accredited-investor verification, and investor whitelisting",
            "Title, deed, and recording issues with the county Register of Deeds",
            "Tennessee Securities Division notice filings and state blue-sky compliance",
            "Distributions, K-1 reporting, and secondary trading through registered venues",
        ],
        "structures": [
            {"name": "Single-Asset SPV LLC",
             "summary": "The property is deeded to a new LLC and investors buy tokenized "
                        "membership interests. Title stays on the county record; ownership "
                        "changes happen on-chain at the entity level.",
             "fits": "One building, like a duplex in East Nashville, a mixed-use lot in Murfreesboro."},
            {"name": "Tennessee Series LLC",
             "summary": "One master LLC with a separate series for each property, each with "
                        "its own token, investors, and liability shield. Fewer formations and "
                        "cleaner reporting.",
             "fits": "Sponsors tokenizing a portfolio of long- or short-term rentals."},
            {"name": "Delaware Statutory Trust (DST)",
             "summary": "Investors hold tokenized beneficial interests in a trust that owns "
                        "the property. A properly structured DST can qualify as replacement "
                        "property in a Section 1031 exchange.",
             "fits": "Stabilized, net-leased commercial property and 1031 investors."},
            {"name": "Tokenized Fund / Reg A+ REIT",
             "summary": "A pooled vehicle owning several properties, offered to the public, "
                        "including non-accredited investors, under Reg A+ Tier 2, with "
                        "ongoing SEC reporting.",
             "fits": "Larger raises aimed at retail investors."},
            {"name": "Tokenized Debt / Mortgage Note",
             "summary": "Investors fund a loan secured by a deed of trust and receive "
                        "tokenized notes paying interest, with no equity in the property itself.",
             "fits": "Developers and renovators who want financing without giving up equity."},
            {"name": "Revenue-Share Token",
             "summary": "Holders receive a share of rental income for a defined term while the "
                        "owner keeps title. Almost always a security.",
             "fits": "Owners raising capital against cash flow rather than the asset."},
        ],
        "process": [
            {"title": "Asset and title diligence",
             "detail": "Title search, existing liens and lender consent, zoning, short-term "
                       "rental permits, and valuation."},
            {"title": "Structure selection",
             "detail": "Entity, tax classification, and securities exemption chosen together "
                       "because each constrains the others."},
            {"title": "Offering documents",
             "detail": "PPM or offering circular, operating or trust agreement, subscription "
                       "documents, and the legal terms the token represents."},
            {"title": "Smart contract legal review",
             "detail": "Confirm the token's transfer restrictions, lockups, and distributions "
                       "match the legal documents, alongside an independent code audit."},
            {"title": "Investor onboarding",
             "detail": "KYC/AML, accreditation verification, whitelisting, and Form D plus "
                       "Tennessee and other state notice filings."},
            {"title": "Issuance and ongoing compliance",
             "detail": "Cap table and transfer-agent setup, distributions, annual reporting, "
                       "and resales through compliant venues."},
        ],
        "fees": [
            {"tier": "Asset value under $500K", "fee": "5%"},
            {"tier": "$500K – $2M",             "fee": "3%"},
            {"tier": "$2M – $10M",              "fee": "1.5%"},
            {"tier": "$10M and above",          "fee": "Custom"},
        ],
        "fees_note": "Full-service legal fee, confirmed in writing after asset review. A $2,500 "
                     "retainer deposit begins the engagement. Smart-contract audit, appraisal, "
                     "and CPA fees are billed separately by those providers.",
        "faqs": [
            {"q": "Does tokenizing a property change the deed?",
             "a": "Usually the property is deeded once into the owning entity and that deed is "
                  "recorded with the county Register of Deeds. After that, token transfers move "
                  "interests in the entity, not the land, so each trade needs no new deed."},
            {"q": "Can non-accredited investors buy?",
             "a": "Under Reg D 506(c), no. Under Reg CF or Reg A+, yes, with more disclosure "
                  "and, for Reg A+, SEC qualification of the offering."},
            {"q": "Can token holders resell?",
             "a": "Reg D securities are restricted under Rule 144 for a holding period. After "
                  "that, resales generally go through a registered broker-dealer or alternative "
                  "trading system. The token's code enforces these limits."},
            {"q": "What if the property has a mortgage?",
             "a": "Most mortgages have a due-on-sale clause that a transfer to an LLC can "
                  "trigger. Lender consent or a refinance comes before the transfer."},
            {"q": "How are investors taxed?",
             "a": "An LLC taxed as a partnership issues K-1s and passes income and depreciation "
                  "through to investors. We coordinate the structure with your CPA."},
        ],
    },
    "family-law": {
        "name":       "Family & Estate Planning",
        "tagline":    "Divorce, custody, and parenting plans, plus the wills, trusts, and "
                      "guardianships that protect your family for the long run.",
        "case_types": ["Family Law — Divorce", "Family Law — Child Custody",
                       "Family Law — Other", "Estate Planning"],
        "helps": [
            'Explains Tennessee custody, support, and property rules before you agree to anything.',
            "Builds a parenting plan centered on your children's stability.",
            'Finds and values every marital asset, including crypto and business interests.',
            "Represents you in mediation and in court, and seeks emergency protection when it's needed.",
            "Updates your will, beneficiaries, and guardianship choices so your plan matches your family after a divorce, marriage, or new child.",
        ],
        "focus": [
            "Tennessee custody factors (T.C.A. § 36-6-106) and parenting plans",
            "Child support guidelines and alimony types (T.C.A. § 36-5-121)",
            "Multi-state jurisdiction issues under the UCCJEA and UIFSA",
            "Domestic violence protections and emergency orders",
            "Finding and dividing cryptocurrency and digital assets in divorce",
            "Wills, trusts, and guardianship nominations for minor children",
            "Powers of attorney and healthcare directives",
            "Prenuptial and postnuptial agreements",
        ],
        "local": "Parents with minor children must generally complete a parenting education "
                 "class and attempt mediation before a contested Tennessee divorce goes to trial.",
        "faqs": [
            {"q": "How long does a Tennessee divorce take?",
             "a": "There is a 60-day waiting period without children and 90 days with children. "
                  "Uncontested divorces can finish shortly after; contested ones take longer."},
            {"q": "Can crypto be hidden in a divorce?",
             "a": "It is harder than people think. Exchange records, tax filings, and on-chain "
                  "analysis often reveal it."},
        ],
    },
    "personal-injury": {
        "name":       "Personal Injury & Liabilities",
        "tagline":    "Auto, premises, product, and negligence claims across Middle Tennessee, "
                      "from first demand through trial.",
        "case_types": ["Personal Injury"],
        "helps": [
            "Preserves evidence and protects Tennessee's one-year filing deadline.",
            "Deals with the insurance companies so a recorded statement doesn't undercut your claim.",
            'Documents medical bills, lost wages, and future care so the claim is valued in full.',
            'Negotiates a settlement, or files suit and takes the case to trial.',
        ],
        "focus": [
            "Tennessee's modified comparative fault rule (T.C.A. § 29-11-103)",
            "Healthcare Liability Act pre-suit requirements for medical claims",
            "Applicable statutes of limitations and filing deadlines",
            "When expert testimony is required to prove the claim",
            "Premises liability for unsafe property conditions",
            "Product liability for defective products",
        ],
        "local": "Tennessee gives most injury victims only one year to file suit, one of the "
                 "shortest deadlines in the country. Crashes on I-24, I-40, and I-65 often "
                 "involve commercial carriers with their own insurers and evidence rules.",
        "faqs": [
            {"q": "How much does it cost to hire you?",
             "a": "Injury cases are typically handled on a contingency fee: no fee unless "
                  "there is a recovery. Terms are set out in a written agreement."},
            {"q": "What if I was partly at fault?",
             "a": "You can still recover if you were less than 50% at fault; your award is "
                  "reduced by your share."},
        ],
    },
    "estate-business": {
        "name":       "Crypto Estate & Future Asset Planning",
        "tagline":    "Wills, trusts, and key-access plans for crypto, tokenized property, "
                      "digital IP, and royalties: the assets you own today and the ones "
                      "you'll own next.",
        "case_types": ["Estate Planning"],
        "helps": [
            "Inventories everything you own, from wallets and tokenized interests to royalties and online accounts, so nothing is lost.",
            "Places assets in trusts that avoid probate and pass to your family privately and quickly.",
            "Gives your executor legal authority and a secure path to digital assets, without exposing your keys today.",
            "Keeps the plan current as you acquire new kinds of assets, marry, have children, or start a business.",
        ],
        "overview":   "Most estate plans were written for a house, a bank account, and a "
                      "retirement fund. Today's families also hold cryptocurrency, tokenized "
                      "real estate, music and content royalties, domain names, and stakes in "
                      "startups. These assets can vanish if no one has the keys or the legal "
                      "authority to reach them. We plan for what you have and for what is "
                      "coming.",
        "focus": [
            "Wills, trusts, and probate-avoidance strategies",
            "Business entity formation and succession planning",
            "Fiduciary and guardian appointments",
            "Digital-asset and cryptocurrency inheritance: crypto wills and multi-sig vaults",
            "Fiduciary access to digital accounts under Tennessee law",
            "Trusts that can hold tokenized real estate and digital securities",
            "Royalties, catalogs, and digital IP: music, content, and AI-assisted works",
            "Powers of attorney and incapacity plans that cover wallets and online accounts",
        ],
        "structures": [
            {"name": "Revocable Living Trust",
             "summary": "Holds your assets during life and passes them at death without probate. "
                        "Can own LLC interests, tokenized property, and digital accounts.",
             "fits": "Most families who want privacy and a faster transfer."},
            {"name": "Digital Asset Access Plan",
             "summary": "A letter of instruction, multi-signature or custodial arrangements, and "
                        "fiduciary authority that let your executor reach crypto without anyone "
                        "holding your keys today.",
             "fits": "Anyone holding self-custodied crypto or NFTs."},
            {"name": "Tennessee Investment Services Trust",
             "summary": "Tennessee's self-settled asset-protection trust: you can remain a "
                        "beneficiary while shielding assets from future creditors, if formed "
                        "correctly and in advance.",
             "fits": "Founders, investors, and professionals with liability exposure."},
            {"name": "Long-Term (Dynasty) Trust",
             "summary": "Tennessee allows trusts to last for generations, keeping appreciating "
                        "assets (tokens, equity, real estate) in the family and out of "
                        "repeated estate tax.",
             "fits": "Assets expected to grow significantly over time."},
            {"name": "Family Holding LLC",
             "summary": "Centralizes rental properties, tokenized interests, or a business under "
                        "one entity with a succession plan written into the operating agreement.",
             "fits": "Families with multiple properties or a family business."},
            {"name": "Tennessee Community Property Trust",
             "summary": "Lets married couples treat trust assets as community property, which can "
                        "produce a full basis step-up at the first spouse's death.",
             "fits": "Couples holding highly appreciated assets, including crypto."},
        ],
        "process": [
            {"title": "Asset inventory",
             "detail": "Traditional and digital assets alike: where they are, how they're held, "
                       "and who can reach them."},
            {"title": "Goals conversation",
             "detail": "Who should inherit, who should decide, and what you want to protect "
                       "against."},
            {"title": "Plan documents",
             "detail": "Will, trusts, powers of attorney, healthcare directives, and digital "
                       "access instructions."},
            {"title": "Funding the plan",
             "detail": "Retitling property and accounts into trusts, the step most plans skip."},
            {"title": "Periodic review",
             "detail": "A check-in when the law changes or your assets do."},
        ],
        "faqs": [
            {"q": "What happens to my crypto when I die?",
             "a": "If no one can access your keys, it may be lost for good. A crypto estate "
                  "plan documents access without exposing keys while you're alive."},
            {"q": "Can a trust own tokenized real estate?",
             "a": "Yes. A trust can hold LLC interests or digital securities, as long as the "
                  "token's transfer rules and investor whitelist allow the trust as a holder."},
            {"q": "Do I need a will if I have a trust?",
             "a": "Yes. A short 'pour-over' will catches anything left outside the trust and "
                  "names guardians for minor children."},
            {"q": "Should my small business be an LLC?",
             "a": "Usually. An LLC separates business and personal liability. We'll also look "
                  "at Tennessee franchise and excise tax and whether an S-election makes sense."},
        ],
    },

}


# Display order: crypto estate planning and emerging tech first, then litigation.
_ORDER = [
    "estate-business", "ai-emerging-tech", "defi-digital-assets", "stablecoins",
    "real-estate-tokenization",
    "criminal-defense", "civil-rights", "family-law", "personal-injury",
]
PRACTICE_AREAS = {slug: PRACTICE_AREAS[slug] for slug in _ORDER}


# ── Emerging Tech hub (/emerging-tech) ───────────────────────────────────────
# The practice areas the hub links into, and the expandable "what's changing"
# briefings underneath them.
EMERGING_TECH_AREAS = [
    "estate-business", "ai-emerging-tech", "defi-digital-assets", "stablecoins",
    "real-estate-tokenization",
]

EMERGING_TECH_TOPICS = [
    {"label": "AI", "title": "Tennessee's ELVIS Act",
     "teaser": "AI voice and likeness cloning, and who is liable for it.",
     "body": "The Ensuring Likeness, Voice, and Image Security Act (2024) adds a person's voice "
             "to Tennessee's right of publicity. It creates liability not only for people who "
             "publish an unauthorized AI clone, but for tools whose primary purpose is producing "
             "one. Artists, labels, studios, and AI developers in Nashville all need to know "
             "where the lines are."},
    {"label": "AI", "title": "Who owns AI-generated work",
     "teaser": "Copyright, training data, and what your contracts say.",
     "body": "The U.S. Copyright Office requires human authorship, so material generated "
             "entirely by AI may not be protected. Works that combine human creativity with AI "
             "assistance can be. Meanwhile, litigation over training data is unresolved, which "
             "makes vendor indemnities and output-ownership clauses the practical protection "
             "for most businesses."},
    {"label": "Privacy", "title": "Tennessee Information Protection Act",
     "teaser": "Tennessee's consumer data privacy law and AI.",
     "body": "Tennessee's comprehensive privacy law gives consumers rights to access, correct, "
             "delete, and opt out of certain uses of their personal data, and requires covered "
             "businesses to run assessments for higher-risk processing. AI systems trained on "
             "or making decisions about customers are a common trigger."},
    {"label": "AI", "title": "The EU AI Act for U.S. companies",
     "teaser": "When a Nashville company has to follow European AI rules.",
     "body": "If your AI product or its output is used in the European Union, the EU AI Act can "
             "apply regardless of where you are based. It sorts AI uses by risk, bans some "
             "outright, and imposes documentation and transparency duties on others. Obligations "
             "phase in over several years."},
    {"label": "Blockchain", "title": "Is your token a security?",
     "teaser": "The Howey test, exemptions, and a shifting federal posture.",
     "body": "Federal regulators' approach to crypto has shifted repeatedly, but the Howey test "
             "still decides whether a token sale is an investment contract. A written analysis "
             "before launch, and an exemption such as Reg D, Reg A+, or Reg CF when the answer "
             "is yes, remains the safest path."},
    {"label": "Stablecoins", "title": "Stablecoins and the GENIUS Act",
     "teaser": "The first federal framework for digital dollars, and the growth it unlocks.",
     "body": "The GENIUS Act (2025) sets licensing, one-to-one reserve, and disclosure rules for "
             "payment stablecoin issuers and bars issuers from paying holders interest. With "
             "clearer rules, banks, payment companies, and merchants are moving in, making "
             "stablecoins a practical way to settle payments faster and cheaper. Regulators are "
             "still finalizing the details."},
    {"label": "Tax", "title": "Crypto yield and taxes",
     "teaser": "Staking rewards, DeFi yield, and the new Form 1099-DA.",
     "body": "Staking rewards are ordinary income when received, and selling crypto later "
             "creates capital gain or loss. Brokers now report crypto sales to the IRS on Form "
             "1099-DA, so missing cost basis or unreported yield is easier for the IRS to spot. "
             "Tennessee has no state income tax on wages or investment income, but federal "
             "rules apply in full."},
    {"label": "Blockchain", "title": "Tennessee's DAO law",
     "teaser": "Decentralized organizations as Tennessee LLCs.",
     "body": "Tennessee lets an LLC operate as a decentralized organization, governed by its "
             "members or by smart contract, with liability protection for members. For "
             "Tennessee-based communities it can be a simpler home than Wyoming or an offshore "
             "foundation."},
    {"label": "Tokenization", "title": "Tokenized real-world assets",
     "teaser": "Real estate, debt, and revenue on a blockchain.",
     "body": "Tokenization puts ownership of real estate, loans, or income streams into "
             "digital securities that can be issued and transferred on-chain. The technology is "
             "new, but the law is familiar: entity formation, securities exemptions, title, and "
             "transfer restrictions all still apply."},
    {"label": "Planning", "title": "Digital assets when you die",
     "teaser": "Keys, accounts, and fiduciary access in Tennessee.",
     "body": "Tennessee law gives executors and trustees a path to digital accounts, but only "
             "if your documents grant it, and no law can recover crypto whose keys are lost. A "
             "digital-asset plan pairs legal authority with a secure, practical way in."},
]
