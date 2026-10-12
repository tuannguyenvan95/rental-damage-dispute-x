import pytest
import json
from gltest import *
from conftest import sim_installMocks


@pytest.fixture
def contract(direct_deploy):
    return direct_deploy("contracts/rental_damage_dispute_x.py")


def test_initial_state_and_domains(contract, direct_vm, direct_alice, direct_bob):
    # Initial state assertions
    assert contract.get_lease_count() == 0
    owner_str = contract.get_owner().lower()
    expected_sender = direct_vm.sender.hex().lower() if isinstance(direct_vm.sender, bytes) else str(direct_vm.sender).lower()
    if not expected_sender.startswith("0x"):
        expected_sender = "0x" + expected_sender
    assert owner_str == expected_sender

    # Default appraisal & inspection domains
    assert contract.is_inspector_allowed("repair-reports.com") is True
    assert contract.is_inspector_allowed("www.repair-reports.com") is True
    assert contract.is_inspector_allowed("certified-appraisal.org") is True
    assert contract.is_inspector_allowed("autocheck.com") is True
    assert contract.is_inspector_allowed("carfax.com") is True
    assert contract.is_inspector_allowed("dekra-claims.com") is True
    assert contract.is_inspector_allowed("mock-inspection.genlayer.com") is True
    assert contract.is_inspector_allowed("untrusted-garage.xyz") is False

    # Owner adds custom allowed inspector
    contract.add_allowed_inspector("garage-certified.io")
    assert contract.is_inspector_allowed("garage-certified.io") is True

    # Owner removes allowed inspector
    contract.remove_allowed_inspector("garage-certified.io")
    assert contract.is_inspector_allowed("garage-certified.io") is False

    # Non-owner cannot add inspector domain
    direct_vm.sender = direct_bob
    with pytest.raises(Exception, match="Only owner can add allowed domains"):
        contract.add_allowed_inspector("scam-appraisal.org")

    # Non-owner cannot remove inspector domain
    with pytest.raises(Exception, match="Only owner can remove allowed domains"):
        contract.remove_allowed_inspector("garage-certified.io")


def test_create_lease_success(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 2500

    future_end = 2000000000

    lid = contract.create_lease(
        host_owner=direct_bob,
        asset_identifier="VIN-1HGCR2F83HA000123",
        rental_end_timestamp=future_end
    )

    assert lid == "1"
    assert contract.get_lease_count() == 1

    lease_data = json.loads(contract.get_lease("1"))
    assert lease_data["lease_id"] == "1"
    assert lease_data["host_owner"] == direct_bob.as_hex.lower()
    assert lease_data["renter_guest"] == direct_alice.as_hex.lower()
    assert lease_data["asset_identifier"] == "VIN-1HGCR2F83HA000123"
    assert lease_data["deposit_amount"] == "2500"
    assert lease_data["status"] == "ACTIVE"
    assert lease_data["verdict"] == "PENDING"
    assert lease_data["host_payout"] == "0"
    assert lease_data["renter_refund"] == "0"
    assert lease_data["rental_end_timestamp"] == str(future_end)


def test_create_lease_validation_failures(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice

    # 1. Zero security deposit
    direct_vm.value = 0
    with pytest.raises(Exception, match="Security deposit must be greater than 0 GEN"):
        contract.create_lease(
            host_owner=direct_bob,
            asset_identifier="VIN-1HGCR2F83HA000123",
            rental_end_timestamp=2000000000
        )

    # 2. Too short asset identifier
    direct_vm.value = 1000
    with pytest.raises(Exception, match="asset_identifier is too short"):
        contract.create_lease(
            host_owner=direct_bob,
            asset_identifier="ABC",
            rental_end_timestamp=2000000000
        )

    # 3. Renter cannot be the same as host
    with pytest.raises(Exception, match="Renter and host cannot be the same address"):
        contract.create_lease(
            host_owner=direct_alice,
            asset_identifier="VIN-1HGCR2F83HA000123",
            rental_end_timestamp=2000000000
        )


def test_release_deposit_by_host_success(contract, direct_vm, direct_alice, direct_bob):
    # Renter Alice locks deposit
    direct_vm.sender = direct_alice
    direct_vm.value = 3000

    lid = contract.create_lease(
        host_owner=direct_bob,
        asset_identifier="APT-UNIT-402",
        rental_end_timestamp=2000000000
    )

    # Host Bob voluntarily releases deposit
    direct_vm.sender = direct_bob
    contract.release_deposit_by_host(lid)

    lease_data = json.loads(contract.get_lease(lid))
    assert lease_data["status"] == "SETTLED"
    assert lease_data["verdict"] == "NO_DAMAGE_OR_WEAR_TEAR"
    assert lease_data["renter_refund"] == "3000"
    assert lease_data["host_payout"] == "0"
    assert "Host confirmed satisfactory return" in lease_data["reason"]


def test_release_deposit_by_host_failures(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 1500

    lid = contract.create_lease(
        host_owner=direct_bob,
        asset_identifier="APT-UNIT-808",
        rental_end_timestamp=2000000000
    )

    # 1. Non-host caller cannot release deposit
    direct_vm.sender = direct_alice
    with pytest.raises(Exception, match="Only host owner can voluntarily release deposit"):
        contract.release_deposit_by_host(lid)

    # 2. Re-release on already settled lease fails
    direct_vm.sender = direct_bob
    contract.release_deposit_by_host(lid)
    with pytest.raises(Exception, match="Lease is not in ACTIVE state"):
        contract.release_deposit_by_host(lid)

    # 3. Release on non-existent lease fails
    with pytest.raises(Exception, match="Lease not found"):
        contract.release_deposit_by_host("999")


def test_claim_expired_lease_refund_validation(contract, direct_vm, direct_alice, direct_bob):
    from datetime import datetime, timezone, timedelta
    t_start = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    direct_vm.warp(t_start.isoformat())

    direct_vm.sender = direct_alice
    direct_vm.value = 2000

    rental_end = int((t_start + timedelta(days=3)).timestamp())

    lid = contract.create_lease(
        host_owner=direct_bob,
        asset_identifier="VIN-TESLA-MOD3-2024",
        rental_end_timestamp=rental_end
    )

    # 1. Non-renter caller cannot claim expired refund
    direct_vm.sender = direct_bob
    with pytest.raises(Exception, match="Only renter can claim expired lease refund"):
        contract.claim_expired_lease_refund(lid)

    # 2. Non-existent lease fails
    direct_vm.sender = direct_alice
    with pytest.raises(Exception, match="Lease not found"):
        contract.claim_expired_lease_refund("999")

    # 3. Before grace period expires: claim must fail
    with pytest.raises(Exception, match="Inspection grace period has not expired yet"):
        contract.claim_expired_lease_refund(lid)

    # 4. Warp time to 25 hours after lease end (grace period is 24 hours)
    t_after_grace = t_start + timedelta(days=3, hours=25)
    direct_vm.warp(t_after_grace.isoformat())

    # 5. Autonomous renter refund succeeds
    contract.claim_expired_lease_refund(lid)
    lease_data = json.loads(contract.get_lease(lid))
    assert lease_data["status"] == "REFUNDED"
    assert lease_data["renter_refund"] == "2000"
    assert lease_data["host_payout"] == "0"
    assert "Deposit automatically refunded to renter" in lease_data["reason"]

    # 6. Double claim fails
    with pytest.raises(Exception, match="Lease is not in ACTIVE state"):
        contract.claim_expired_lease_refund(lid)


def test_dispute_damage_claim_validation_failures(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 4000

    lid = contract.create_lease(
        host_owner=direct_bob,
        asset_identifier="VIN-1HGCR2F83HA999999",
        rental_end_timestamp=2000000000
    )

    # 1. Non-host caller cannot file dispute
    direct_vm.sender = direct_alice
    with pytest.raises(Exception, match="Only host owner can file a damage dispute"):
        contract.dispute_damage_claim(lid, "https://repair-reports.com/vin-1hgcr2f83ha999999")

    # 2. Non-existent lease fails
    direct_vm.sender = direct_bob
    with pytest.raises(Exception, match="Lease not found"):
        contract.dispute_damage_claim("999", "https://repair-reports.com/vin-1hgcr2f83ha999999")

    # 3. Invalid URL scheme (not http/https)
    with pytest.raises(Exception, match="inspection_report_url must start with http:// or https://"):
        contract.dispute_damage_claim(lid, "ftp://repair-reports.com/vin-1hgcr2f83ha999999")

    # 4. Non-whitelisted inspector domain
    with pytest.raises(Exception, match="not in the allowed domain whitelist"):
        contract.dispute_damage_claim(lid, "https://fraudulent-appraisal-shop.com/vin-1hgcr2f83ha999999")

    # 5. Asset identifier not bound into URL
    with pytest.raises(Exception, match="must canonically contain asset identifier"):
        contract.dispute_damage_claim(lid, "https://repair-reports.com/report-for-some-other-vehicle")


def test_dispute_total_damage_forfeit(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 5000

    asset_id = "VIN-1HGCR2F83HA000123"
    report_url = f"https://www.repair-reports.com/inspections/{asset_id.lower()}/claim-881"

    lid = contract.create_lease(
        host_owner=direct_bob,
        asset_identifier=asset_id,
        rental_end_timestamp=2000000000
    )

    # Install Mocks for web render and LLM jury
    sim_installMocks({
        "web_mocks": {
            ".*repair-reports.com.*": {
                "status": 200,
                "body": f"Official Certified Appraisal for {asset_id}. Severe structural frame damage, deployed airbags, totaled suspension. Repair estimate: $12,450."
            }
        },
        "llm_mocks": {
            ".*": {
                "verdict": "TOTAL_DAMAGE_FORFEIT",
                "confidence": 98,
                "reason": "Severe frame damage and airbag deployment exceeding total deposit threshold."
            }
        }
    }, vm=direct_vm)

    direct_vm.sender = direct_bob
    contract.dispute_damage_claim(lid, report_url)

    lease_data = json.loads(contract.get_lease(lid))
    assert lease_data["status"] == "SETTLED"
    assert lease_data["verdict"] == "TOTAL_DAMAGE_FORFEIT"
    assert lease_data["host_payout"] == "5000"
    assert lease_data["renter_refund"] == "0"
    assert "Severe frame damage" in lease_data["reason"]


def test_dispute_partial_damage_assessed(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 4000

    asset_id = "APT-PENTHOUSE-701"
    report_url = f"https://certified-appraisal.org/reports/residential/{asset_id.lower()}"

    lid = contract.create_lease(
        host_owner=direct_bob,
        asset_identifier=asset_id,
        rental_end_timestamp=2000000000
    )

    sim_installMocks({
        "web_mocks": {
            ".*certified-appraisal.org.*": {
                "status": 200,
                "body": f"Appraisal report for {asset_id}. Broken sliding glass balcony door and stained hardwood floor. Estimated repair bill: $1,600."
            }
        },
        "llm_mocks": {
            ".*": {
                "verdict": "PARTIAL_DAMAGE_ASSESSED",
                "confidence": 90,
                "reason": "Moderate localized damage to balcony door and hardwood requiring partial deduction."
            }
        }
    }, vm=direct_vm)

    direct_vm.sender = direct_bob
    contract.dispute_damage_claim(lid, report_url)

    lease_data = json.loads(contract.get_lease(lid))
    assert lease_data["status"] == "SETTLED"
    assert lease_data["verdict"] == "PARTIAL_DAMAGE_ASSESSED"
    # 50% split: 2000 to host, 2000 refund to guest
    assert lease_data["host_payout"] == "2000"
    assert lease_data["renter_refund"] == "2000"
    assert "Moderate localized damage" in lease_data["reason"]


def test_dispute_no_damage_or_wear_tear(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 3000

    asset_id = "VIN-BMW-M3-COMPETITION"
    report_url = f"https://autocheck.com/vehicle-records/{asset_id.lower()}/return-check"

    lid = contract.create_lease(
        host_owner=direct_bob,
        asset_identifier=asset_id,
        rental_end_timestamp=2000000000
    )

    sim_installMocks({
        "web_mocks": {
            ".*autocheck.com.*": {
                "status": 200,
                "body": f"Return inspection for {asset_id}. Minor micro-scratches on door handle and standard tire tread wear consistent with 400 miles driven. No structural or mechanical faults."
            }
        },
        "llm_mocks": {
            ".*": {
                "verdict": "NO_DAMAGE_OR_WEAR_TEAR",
                "confidence": 95,
                "reason": "Inspection confirms ordinary wear and tear with zero qualifying damage."
            }
        }
    }, vm=direct_vm)

    direct_vm.sender = direct_bob
    contract.dispute_damage_claim(lid, report_url)

    lease_data = json.loads(contract.get_lease(lid))
    assert lease_data["status"] == "SETTLED"
    assert lease_data["verdict"] == "NO_DAMAGE_OR_WEAR_TEAR"
    # 100% refund to guest
    assert lease_data["host_payout"] == "0"
    assert lease_data["renter_refund"] == "3000"
    assert "ordinary wear and tear" in lease_data["reason"]


def test_dispute_offline_or_404_url(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 3500

    asset_id = "VIN-PORSCHE-911-GT3"
    report_url = f"https://dekra-claims.com/reports/{asset_id.lower()}/claim-missing"

    lid = contract.create_lease(
        host_owner=direct_bob,
        asset_identifier=asset_id,
        rental_end_timestamp=2000000000
    )

    sim_installMocks({
        "web_mocks": {
            ".*dekra-claims.com.*": {
                "status": 404,
                "body": "404 Not Found - The appraisal report has been removed or is inaccessible."
            }
        }
    }, vm=direct_vm)

    direct_vm.sender = direct_bob
    contract.dispute_damage_claim(lid, report_url)

    lease_data = json.loads(contract.get_lease(lid))
    assert lease_data["status"] == "SETTLED"
    assert lease_data["verdict"] == "NO_DAMAGE_OR_WEAR_TEAR"
    assert lease_data["host_payout"] == "0"
    assert lease_data["renter_refund"] == "3500"
    assert "offline, blank, or returned 404" in lease_data["reason"]


def test_dispute_llm_markdown_stripping(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 6000

    asset_id = "VIN-AUDI-RS6-AVANT"
    report_url = f"https://carfax.com/inspections/{asset_id.lower()}"

    lid = contract.create_lease(
        host_owner=direct_bob,
        asset_identifier=asset_id,
        rental_end_timestamp=2000000000
    )

    # LLM returns markdown fenced json
    markdown_wrapped_json = """```json
{
  "verdict": "PARTIAL_DAMAGE_ASSESSED",
  "confidence": 88,
  "reason": "Cracked carbon fiber front lip and curbed alloy wheel."
}
```"""

    sim_installMocks({
        "web_mocks": {
            ".*carfax.com.*": {
                "status": 200,
                "body": f"Vehicle damage inspection for {asset_id}. Damaged front bumper lip and curbed right front wheel."
            }
        },
        "llm_mocks": {
            ".*": markdown_wrapped_json
        }
    }, vm=direct_vm)

    direct_vm.sender = direct_bob
    contract.dispute_damage_claim(lid, report_url)

    lease_data = json.loads(contract.get_lease(lid))
    assert lease_data["status"] == "SETTLED"
    assert lease_data["verdict"] == "PARTIAL_DAMAGE_ASSESSED"
    assert lease_data["host_payout"] == "3000"
    assert lease_data["renter_refund"] == "3000"


def test_dispute_custom_whitelisted_domain(contract, direct_vm, direct_alice, direct_bob):
    # Owner whitelists an authorized regional garage
    contract.add_allowed_inspector("authorized-garage-berlin.de")
    assert contract.is_inspector_allowed("authorized-garage-berlin.de") is True

    direct_vm.sender = direct_alice
    direct_vm.value = 1800

    asset_id = "VIN-MERCEDES-C300-DE"
    report_url = f"https://authorized-garage-berlin.de/claims/{asset_id.lower()}/cert"

    lid = contract.create_lease(
        host_owner=direct_bob,
        asset_identifier=asset_id,
        rental_end_timestamp=2000000000
    )

    sim_installMocks({
        "web_mocks": {
            ".*authorized-garage-berlin.de.*": {
                "status": 200,
                "body": f"Official garage repair assessment for {asset_id}. Total engine oil pan puncture and ruined transmission. Total replacement required."
            }
        },
        "llm_mocks": {
            ".*": {
                "verdict": "TOTAL_DAMAGE_FORFEIT",
                "confidence": 99,
                "reason": "Severe mechanical destruction of oil pan and transmission."
            }
        }
    }, vm=direct_vm)

    direct_vm.sender = direct_bob
    contract.dispute_damage_claim(lid, report_url)

    lease_data = json.loads(contract.get_lease(lid))
    assert lease_data["status"] == "SETTLED"
    assert lease_data["verdict"] == "TOTAL_DAMAGE_FORFEIT"
    assert lease_data["host_payout"] == "1800"
    assert lease_data["renter_refund"] == "0"


def test_multiple_concurrent_leases(contract, direct_vm, direct_alice, direct_bob):
    # Alice rents Asset 1 from Bob
    direct_vm.sender = direct_alice
    direct_vm.value = 1000
    lid_1 = contract.create_lease(direct_bob, "VIN-TOYOTA-RAV4-01", 2000000000)

    # Bob rents Asset 2 from Alice
    direct_vm.sender = direct_bob
    direct_vm.value = 2000
    lid_2 = contract.create_lease(direct_alice, "APT-STUDIO-VILLAGE-10", 2000000000)

    assert lid_1 == "1"
    assert lid_2 == "2"
    assert contract.get_lease_count() == 2

    l1 = json.loads(contract.get_lease("1"))
    l2 = json.loads(contract.get_lease("2"))

    assert l1["asset_identifier"] == "VIN-TOYOTA-RAV4-01"
    assert l2["asset_identifier"] == "APT-STUDIO-VILLAGE-10"
    assert l1["deposit_amount"] == "1000"
    assert l2["deposit_amount"] == "2000"


def test_view_functions_and_errors(contract, direct_vm):
    assert contract.get_lease_count() == 0
    assert isinstance(contract.get_current_time(), int)
    assert len(contract.get_owner()) > 0

    with pytest.raises(Exception, match="Lease not found"):
        contract.get_lease("non-existent-id")
