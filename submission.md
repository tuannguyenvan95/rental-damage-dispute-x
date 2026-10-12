# Portal Submission Draft — RentalDamageDisputeX

**Portal Track:** Builder  
**Contribution Type:** Intelligent Contracts  
**Network:** studionet (Chain ID: 61999)  
**Contract Address:** `0xbe46a379bB23C5dd48D56ba76fcA25507A201859`  
**Evidence URL:** `https://github.com/tuannguyenvan95/rental-damage-dispute-x`  

---

### Title
RentalDamageDisputeX — Autonomous Short-Term Rental & Car-Sharing Security Deposit Arbiter

### One-liner (<180 characters)
Autonomous security deposit arbiter for rentals & car-sharing on GenLayer using live repair report scraping and discrete AI damage consensus.

### Description (<1000 characters)
RentalDamageDisputeX is an autonomous security deposit arbiter for decentralized property rentals and peer-to-peer car sharing (decentralized Airbnb/Turo). It eliminates unfair deposit retention and uncompensated property damage without centralized arbiters.

Guests lock deposits in escrow bound to specific asset IDs (VIN/unit) and lease deadlines. When damage occurs, GenLayer validators inspect certified appraisal reports from authorized garages via gl.nondet.web.render and adjudicate claims on-chain using an LLM consensus jury.

Economic determinism is enforced through 100% discrete consensus tiers: TOTAL_DAMAGE_FORFEIT (100% host payout), PARTIAL_DAMAGE_ASSESSED (50% host / 50% guest), and NO_DAMAGE_OR_WEAR_TEAR (100% guest refund). Domain whitelisting, asset binding, and an autonomous safe recovery path after lease expiry guarantee funds are never stuck. Tested with 15 gltest tests, live on studionet: 0xbe46a379bB23C5dd48D56ba76fcA25507A201859.
