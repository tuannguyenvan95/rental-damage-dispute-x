# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
from dataclasses import dataclass
import json


if not hasattr(gl, "UserError"):
    try:
        gl.UserError = gl.vm.UserError
    except Exception:
        pass


def _addr_str(addr: Address) -> str:
    """Safely format an Address instance into a lowercase hex string."""
    try:
        return addr.as_hex.lower()
    except Exception:
        return str(addr).lower()


def _get_sender() -> Address:
    """Safely obtain transaction sender across GenVM runtime versions with static schema fallback."""
    try:
        if hasattr(gl, "message"):
            if hasattr(gl.message, "sender"):
                return gl.message.sender
            if hasattr(gl.message, "sender_address"):
                return gl.message.sender_address
    except Exception:
        pass
    try:
        if hasattr(gl, "message_raw") and isinstance(gl.message_raw, dict):
            sender_raw = gl.message_raw.get("from") or gl.message_raw.get("sender")
            if sender_raw:
                return Address(str(sender_raw))
    except Exception:
        pass
    return Address("0x0000000000000000000000000000000000000000")


def _safe_transfer(recipient: Address, amount: bigint) -> None:
    """Safely disburse native GEN to an address using official GenLayer SDK pattern."""
    if amount <= bigint(0):
        return
    gl.get_contract_at(recipient).emit_transfer(value=u256(int(amount)))


DEFAULT_INSPECTION_DOMAINS = (
    "repair-reports.com",
    "www.repair-reports.com",
    "certified-appraisal.org",
    "autocheck.com",
    "www.autocheck.com",
    "carfax.com",
    "www.carfax.com",
    "dekra-claims.com",
    "mock-inspection.genlayer.com",
)


def _parse_url_host(raw_url: str) -> str:
    """Extract and validate normalized hostname from URL."""
    clean = raw_url.strip()
    if "?" in clean:
        clean = clean.split("?")[0]
    if "#" in clean:
        clean = clean.split("#")[0]
    clean = clean.strip()

    if clean.startswith("https://"):
        rest = clean[8:]
    elif clean.startswith("http://"):
        rest = clean[7:]
    else:
        raise gl.UserError("URL must begin with http:// or https://")

    host = rest.split("/", 1)[0].strip().lower()
    if ":" in host:
        host = host.split(":")[0].strip()
    if not host:
        raise gl.UserError("Invalid URL: missing host")
    return host


@allow_storage
@dataclass
class RentalLease:
    lease_id: str
    host_owner: Address
    renter_guest: Address
    asset_identifier: str
    deposit_amount: bigint
    status: str
    verdict: str
    inspection_report_url: str
    host_payout: bigint
    renter_refund: bigint
    reason: str
    rental_end_timestamp: bigint
    created_at: bigint
    resolved_at: bigint


class Contract(gl.Contract):
    """
    RentalDamageDisputeX: Autonomous Short-Term Rental & Car-Sharing Security Deposit Arbiter
    Track: Real-World Settlement / Agentic Commerce Infrastructure
    """
    owner: Address
    lease_count: bigint
    leases: TreeMap[str, RentalLease]
    custom_allowed_inspectors: TreeMap[str, bool]

    def __init__(self):
        # GenVM automatically initializes TreeMap storage fields to empty.
        self.owner = _get_sender()
        self.lease_count = bigint(0)

    def _get_current_timestamp(self) -> bigint:
        """Derive trusted deterministic execution timestamp from GenLayer transaction context."""
        try:
            from datetime import datetime
            dt_raw = getattr(gl.message, "datetime", None)
            if dt_raw is None and hasattr(gl, "message_raw") and isinstance(gl.message_raw, dict):
                dt_raw = gl.message_raw.get("datetime")
            if dt_raw:
                dt_str = str(dt_raw).strip().replace("Z", "+00:00")
                dt = datetime.fromisoformat(dt_str)
                ts = int(dt.timestamp())
                if ts > 0:
                    return bigint(ts)
        except Exception:
            pass

        try:
            if hasattr(gl, "block") and hasattr(gl.block, "timestamp"):
                ts = int(gl.block.timestamp)
                if ts > 0:
                    return bigint(ts)
        except Exception:
            pass

        return bigint(0)

    def _parse_llm_json(self, text: str) -> dict:
        """Safely parse LLM responses, stripping markdown wrappers if present."""
        try:
            cleaned = str(text).strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            return json.loads(cleaned.strip())
        except Exception as e:
            return {
                "verdict": "NO_DAMAGE_OR_WEAR_TEAR",
                "confidence": 0,
                "reason": f"Failed to parse LLM JSON: {str(e)[:100]}"
            }

    @gl.public.write
    def add_allowed_inspector(self, domain: str) -> None:
        """Owner can add trusted appraisal and garage domains."""
        if _addr_str(_get_sender()) != _addr_str(self.owner):
            raise gl.UserError("Only owner can add allowed domains.")
        clean = domain.strip().lower()
        if len(clean) < 3:
            raise gl.UserError("Invalid domain name.")
        self.custom_allowed_inspectors[clean] = True

    @gl.public.write
    def remove_allowed_inspector(self, domain: str) -> None:
        """Owner can revoke custom allowed appraisal and garage domain."""
        if _addr_str(_get_sender()) != _addr_str(self.owner):
            raise gl.UserError("Only owner can remove allowed domains.")
        clean = domain.strip().lower()
        self.custom_allowed_inspectors[clean] = False

    @gl.public.view
    def is_inspector_allowed(self, domain: str) -> bool:
        """Check if an appraisal domain is whitelisted."""
        clean = domain.strip().lower()
        if clean in DEFAULT_INSPECTION_DOMAINS:
            return True
        try:
            return bool(self.custom_allowed_inspectors[clean])
        except Exception:
            return False

    @gl.public.write.payable
    def create_lease(
        self,
        host_owner: Address,
        asset_identifier: str,
        rental_end_timestamp: int
    ) -> str:
        """
        Renter books asset, locks security deposit in escrow, and specifies rental end deadline.
        """
        deposit = bigint(gl.message.value)
        if deposit <= bigint(0):
            raise gl.UserError("Security deposit must be greater than 0 GEN.")

        clean_asset = asset_identifier.strip().upper()
        if len(clean_asset) < 4:
            raise gl.UserError("asset_identifier is too short.")

        if _addr_str(_get_sender()) == _addr_str(host_owner):
            raise gl.UserError("Renter and host cannot be the same address.")

        end_ts = bigint(rental_end_timestamp)
        now_ts = self._get_current_timestamp()
        if now_ts > bigint(0) and end_ts <= now_ts:
            raise gl.UserError("rental_end_timestamp must be in the future.")

        self.lease_count += bigint(1)
        lid = str(self.lease_count)

        self.leases[lid] = RentalLease(
            lease_id=lid,
            host_owner=host_owner,
            renter_guest=_get_sender(),
            asset_identifier=clean_asset,
            deposit_amount=deposit,
            status="ACTIVE",
            verdict="PENDING",
            inspection_report_url="",
            host_payout=bigint(0),
            renter_refund=bigint(0),
            reason="Lease active. Deposit locked in escrow.",
            rental_end_timestamp=end_ts,
            created_at=self.lease_count,
            resolved_at=bigint(0)
        )

        return lid

    @gl.public.write
    def release_deposit_by_host(self, lease_id: str) -> None:
        """
        Happy Path: Host confirms asset returned in perfect condition and releases deposit back to renter.
        """
        if lease_id not in self.leases:
            raise gl.UserError("Lease not found.")

        lease = self.leases[lease_id]
        if _addr_str(_get_sender()) != _addr_str(lease.host_owner):
            raise gl.UserError("Only host owner can voluntarily release deposit.")

        if lease.status != "ACTIVE":
            raise gl.UserError("Lease is not in ACTIVE state.")

        refund_amt = lease.deposit_amount
        lease.status = "SETTLED"
        lease.verdict = "NO_DAMAGE_OR_WEAR_TEAR"
        lease.renter_refund = refund_amt
        lease.host_payout = bigint(0)
        lease.reason = "Host confirmed satisfactory return and released deposit."
        lease.resolved_at = self.lease_count
        self.leases[lease_id] = lease

        _safe_transfer(lease.renter_guest, refund_amt)

    @gl.public.write
    def claim_expired_lease_refund(self, lease_id: str) -> None:
        """
        Safe Renter Recovery Path:
        If lease passes end timestamp plus grace period without host filing a damage dispute,
        renter can autonomously claim back 100% of their deposit.
        """
        if lease_id not in self.leases:
            raise gl.UserError("Lease not found.")

        lease = self.leases[lease_id]
        if _addr_str(_get_sender()) != _addr_str(lease.renter_guest):
            raise gl.UserError("Only renter can claim expired lease refund.")

        if lease.status != "ACTIVE":
            raise gl.UserError("Lease is not in ACTIVE state.")

        now_ts = self._get_current_timestamp()
        # 24-hour grace period after rental end for host to inspect
        grace_period = bigint(86400)
        if now_ts > bigint(0) and now_ts <= (lease.rental_end_timestamp + grace_period):
            raise gl.UserError("Inspection grace period has not expired yet.")

        refund_amt = lease.deposit_amount
        lease.status = "REFUNDED"
        lease.verdict = "NO_DAMAGE_OR_WEAR_TEAR"
        lease.renter_refund = refund_amt
        lease.host_payout = bigint(0)
        lease.reason = "Lease expired without dispute. Deposit automatically refunded to renter."
        lease.resolved_at = self.lease_count
        self.leases[lease_id] = lease

        _safe_transfer(lease.renter_guest, refund_amt)

    @gl.public.write
    def dispute_damage_claim(self, lease_id: str, inspection_report_url: str) -> None:
        """
        Host reports damage and submits official repair appraisal report.
        Validators scrape report and adjudicate discrete deposit deduction.
        """
        if lease_id not in self.leases:
            raise gl.UserError("Lease not found.")

        lease = self.leases[lease_id]
        if _addr_str(_get_sender()) != _addr_str(lease.host_owner):
            raise gl.UserError("Only host owner can file a damage dispute.")

        if lease.status != "ACTIVE":
            raise gl.UserError("Lease is not in ACTIVE state.")

        clean_url = inspection_report_url.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            raise gl.UserError("inspection_report_url must start with http:// or https://")

        # Canonical Domain Whitelist
        host = _parse_url_host(clean_url)
        is_allowed = host in DEFAULT_INSPECTION_DOMAINS
        if not is_allowed:
            try:
                is_allowed = bool(self.custom_allowed_inspectors[host])
            except Exception:
                is_allowed = False
        if not is_allowed:
            raise gl.UserError(f"Inspector host '{host}' is not in the allowed domain whitelist.")

        # Asset Identifier Binding (URL must link to the specified asset)
        if lease.asset_identifier.lower() not in clean_url.lower():
            raise gl.UserError(f"Inspection URL must canonically contain asset identifier '{lease.asset_identifier}'.")

        asset_local = str(lease.asset_identifier)
        url_local = str(clean_url)

        def leader_fn():
            web_content = ""
            try:
                res = gl.nondet.web.render(url_local, mode="text")
                if hasattr(res, "content"):
                    web_content = res.content
                elif isinstance(res, dict) and "body" in res:
                    web_content = res["body"]
                else:
                    web_content = str(res)
            except Exception:
                web_content = ""

            lower_web = web_content[:500].lower() if web_content else ""
            if len(web_content.strip()) < 15 or "404 not found" in lower_web or "report not found" in lower_web:
                return {
                    "verdict": "NO_DAMAGE_OR_WEAR_TEAR",
                    "confidence": 100,
                    "reason": "Inspection appraisal URL is offline, blank, or returned 404."
                }

            snippet = web_content[:4000]

            prompt = f"""You are the Autonomous Vehicle & Property Rental Damage Arbiter on GenLayer.
Evaluate the certified damage appraisal report for ASSET: {asset_local}.
Determine the discrete severity tier of damage attributable to the renter during the lease.

OFFICIAL INSPECTION & REPAIR REPORT CONTENT:
\"\"\"
{snippet}
\"\"\"

DISCRETE CLASSIFICATION RULES:
- "TOTAL_DAMAGE_FORFEIT": The appraisal proves severe structural/mechanical damage or total loss clearly exceeding normal usage, requiring 100% deposit forfeiture to the host.
- "PARTIAL_DAMAGE_ASSESSED": The report identifies moderate localized damage (e.g. cracked bumper, broken furniture, heavy staining) requiring significant repair, warranting a 50% deposit compensation to host and 50% refund to renter.
- "NO_DAMAGE_OR_WEAR_TEAR": The report shows no verifiable damage, only ordinary wear and tear, or lacks clear repair estimates for this specific asset.

OUTPUT FORMAT:
Respond ONLY with a VALID JSON object (no markdown, no backticks):
{{
  "verdict": "TOTAL_DAMAGE_FORFEIT" | "PARTIAL_DAMAGE_ASSESSED" | "NO_DAMAGE_OR_WEAR_TEAR",
  "confidence": <integer from 0 to 100>,
  "reason": "<concise explanation max 220 characters>"
}}"""

            try:
                raw_res = gl.nondet.exec_prompt(prompt, response_format="json")
                parsed = None
                if isinstance(raw_res, dict):
                    parsed = raw_res
                elif hasattr(raw_res, "content") and isinstance(raw_res.content, dict):
                    parsed = raw_res.content
                else:
                    text = raw_res.content if hasattr(raw_res, "content") else str(raw_res)
                    cleaned = str(text).strip()
                    if cleaned.startswith("```json"):
                        cleaned = cleaned[7:]
                    elif cleaned.startswith("```"):
                        cleaned = cleaned[3:]
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                    parsed = json.loads(cleaned.strip())

                verdict_candidate = str(parsed.get("verdict", "NO_DAMAGE_OR_WEAR_TEAR")).strip().upper()
                valid_verdicts = ("TOTAL_DAMAGE_FORFEIT", "PARTIAL_DAMAGE_ASSESSED", "NO_DAMAGE_OR_WEAR_TEAR")
                if verdict_candidate not in valid_verdicts:
                    verdict_candidate = "NO_DAMAGE_OR_WEAR_TEAR"

                try:
                    conf = int(parsed.get("confidence", 0))
                    conf = max(0, min(100, conf))
                except Exception:
                    conf = 50

                reason_str = str(parsed.get("reason", "Appraisal evaluated by autonomous jury."))[:220]

                return {
                    "verdict": verdict_candidate,
                    "confidence": conf,
                    "reason": reason_str
                }
            except Exception as e:
                return {
                    "verdict": "NO_DAMAGE_OR_WEAR_TEAR",
                    "confidence": 0,
                    "reason": f"Evaluation error: {str(e)[:100]}"
                }

        def validator_fn(leader_res) -> bool:
            if not isinstance(leader_res, gl.vm.Return):
                return False
            leader = leader_res.calldata
            if not isinstance(leader, dict) or "verdict" not in leader:
                return False

            valid_verdicts = ("TOTAL_DAMAGE_FORFEIT", "PARTIAL_DAMAGE_ASSESSED", "NO_DAMAGE_OR_WEAR_TEAR")
            l_verdict = str(leader.get("verdict", "")).strip().upper()
            if l_verdict not in valid_verdicts:
                return False

            mine = leader_fn()
            m_verdict = str(mine.get("verdict", "")).strip().upper()

            # DISCRETE EQUIVALENCE: 100% agreement on exact damage outcome
            return l_verdict == m_verdict

        adjudication_res = gl.vm.run_nondet(leader_fn, validator_fn)
        if isinstance(adjudication_res, dict):
            final_res = adjudication_res
        else:
            final_res = self._parse_llm_json(str(adjudication_res))

        verdict = str(final_res.get("verdict", "NO_DAMAGE_OR_WEAR_TEAR")).strip().upper()
        valid_verdicts = ("TOTAL_DAMAGE_FORFEIT", "PARTIAL_DAMAGE_ASSESSED", "NO_DAMAGE_OR_WEAR_TEAR")
        if verdict not in valid_verdicts:
            verdict = "NO_DAMAGE_OR_WEAR_TEAR"

        reason = str(final_res.get("reason", "Consensus concluded."))

        lease.status = "SETTLED"
        lease.verdict = verdict
        lease.inspection_report_url = clean_url
        lease.reason = reason
        lease.resolved_at = self.lease_count

        total_dep = lease.deposit_amount

        if verdict == "TOTAL_DAMAGE_FORFEIT":
            lease.host_payout = total_dep
            lease.renter_refund = bigint(0)
            self.leases[lease_id] = lease
            _safe_transfer(lease.host_owner, total_dep)

        elif verdict == "PARTIAL_DAMAGE_ASSESSED":
            host_share = total_dep // bigint(2)
            renter_share = total_dep - host_share
            lease.host_payout = host_share
            lease.renter_refund = renter_share
            self.leases[lease_id] = lease
            _safe_transfer(lease.host_owner, host_share)
            _safe_transfer(lease.renter_guest, renter_share)

        else:
            lease.host_payout = bigint(0)
            lease.renter_refund = total_dep
            self.leases[lease_id] = lease
            _safe_transfer(lease.renter_guest, total_dep)

    @gl.public.view
    def get_lease(self, lease_id: str) -> str:
        """Retrieve details of a rental lease as a JSON string."""
        if lease_id not in self.leases:
            raise gl.UserError("Lease not found.")
        l = self.leases[lease_id]
        return json.dumps({
            "lease_id": l.lease_id,
            "host_owner": _addr_str(l.host_owner),
            "renter_guest": _addr_str(l.renter_guest),
            "asset_identifier": l.asset_identifier,
            "deposit_amount": str(l.deposit_amount),
            "status": l.status,
            "verdict": l.verdict,
            "inspection_report_url": l.inspection_report_url,
            "host_payout": str(l.host_payout),
            "renter_refund": str(l.renter_refund),
            "reason": l.reason,
            "rental_end_timestamp": str(l.rental_end_timestamp),
            "created_at": str(l.created_at),
            "resolved_at": str(l.resolved_at)
        })

    @gl.public.view
    def get_current_time(self) -> int:
        """Retrieve current contract execution timestamp."""
        return int(str(self._get_current_timestamp()))

    @gl.public.view
    def get_lease_count(self) -> int:
        return int(self.lease_count)

    @gl.public.view
    def get_owner(self) -> str:
        return _addr_str(self.owner)
