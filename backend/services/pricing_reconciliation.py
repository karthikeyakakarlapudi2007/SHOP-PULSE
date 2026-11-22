"""Product classification reconciliation service (Stage 3A.1).

Provides safe, atomic, idempotent reconciliation of audited product pricing statuses and basis fields.
Matches strictly by full 32-character Product ID + Shop ID.
Never modifies products by name alone. Fails closed on ambiguity.
Guarantees atomic rollback on transaction errors; zero partial commits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging
from uuid import UUID

from sqlalchemy.orm import Session
from db.models.product import Product

logger = logging.getLogger(__name__)

@dataclass
class ReconciliationReport:
    total_audited: int = 0
    matched_count: int = 0
    unmatched_count: int = 0
    conflict_count: int = 0
    status_counts: Dict[str, int] = field(default_factory=dict)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False
    error: Optional[str] = None

# Exact audited 65 product definitions from rigorous production evidence audit
AUDITED_65_PRODUCTS: Dict[str, Dict[str, Any]] = {
    "e000ab09cc204ec59e2cb4b4c858c6d9": {
        "id": "e000ab09cc204ec59e2cb4b4c858c6d9",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Aashirvaad Atta 5 kg",
        "unit": "bag",
        "basis_qty": 1.0,
        "basis_unit": "bag",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹300.00 confirmed by stored evidence (3 purchases, 0 sales, MRP: None).",
    },
    "8170bf3046df4e64a14663002b4fa74d": {
        "id": "8170bf3046df4e64a14663002b4fa74d",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Britannia Marie Gold 800 g",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹84.00 confirmed by stored evidence (3 purchases, 0 sales, MRP: None).",
    },
    "10caeafe4c864e5590ecb99c01b18d05": {
        "id": "10caeafe4c864e5590ecb99c01b18d05",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Colgate Toothpaste 200 g",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹102.00 confirmed by stored evidence (3 purchases, 0 sales, MRP: None).",
    },
    "304bf1814cfe4696995c3778824c4e3c": {
        "id": "304bf1814cfe4696995c3778824c4e3c",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Fortune Besan 500 GM",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹78.00 confirmed by stored evidence (1 purchases, 0 sales, MRP: 90.0).",
    },
    "98cecae7af374265ba7413e2e6da6902": {
        "id": "98cecae7af374265ba7413e2e6da6902",
        "shop_id": "ec51853a955b4fe3b277afcad5ae59a9",
        "name": "Fortune Sunflower Oil (1L)",
        "unit": "pouch",
        "basis_qty": 1.0,
        "basis_unit": "pouch",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹165.00 confirmed by stored evidence (0 purchases, 1 sales, MRP: None).",
    },
    "c43504cef90b44f9934215e2b84b291e": {
        "id": "c43504cef90b44f9934215e2b84b291e",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Fortune Sunflower Oil 1 L",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹180.00 confirmed by stored evidence (3 purchases, 0 sales, MRP: None).",
    },
    "686e2204fbe7491c863d5319692d2261": {
        "id": "686e2204fbe7491c863d5319692d2261",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Hello Organic Chana Dal 1 KG",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹140.00 confirmed by stored evidence (1 purchases, 0 sales, MRP: 160.0).",
    },
    "50f1000e6aa3438a9eee50d8178fbabb": {
        "id": "50f1000e6aa3438a9eee50d8178fbabb",
        "shop_id": "ffc62e9ff2894d47b605e0cbf0bd2990",
        "name": "PAALU",
        "unit": "pkts",
        "basis_qty": 1.0,
        "basis_unit": "pkts",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹50.00 confirmed by stored evidence (0 purchases, 1 sales, MRP: None).",
    },
    "a9f7f6fd684f46a5a2b036f21473ca8b": {
        "id": "a9f7f6fd684f46a5a2b036f21473ca8b",
        "shop_id": "62142ac63acb4816a0d531759d641d4c",
        "name": "Parle-G",
        "unit": "pack",
        "basis_qty": 1.0,
        "basis_unit": "pack",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹10.00 confirmed by stored evidence (0 purchases, 1 sales, MRP: None).",
    },
    "bcd2fd3da48742249b188d5fd1f29cd9": {
        "id": "bcd2fd3da48742249b188d5fd1f29cd9",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Parle-G Biscuit 800 g",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹72.00 confirmed by stored evidence (3 purchases, 0 sales, MRP: None).",
    },
    "91a2ea523b414e25bf998b3fa99fa3d2": {
        "id": "91a2ea523b414e25bf998b3fa99fa3d2",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Rajamm",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹50.00 confirmed by stored evidence (1 purchases, 0 sales, MRP: 58.0).",
    },
    "bea418e5e01e4a6697e8c2f528b00928": {
        "id": "bea418e5e01e4a6697e8c2f528b00928",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Rajamm",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹50.00 confirmed by stored evidence (1 purchases, 0 sales, MRP: 58.0).",
    },
    "0fbfab4206754e05b589f1f3d80b80ef": {
        "id": "0fbfab4206754e05b589f1f3d80b80ef",
        "shop_id": "359a9f0c36514979b420b841c0a0a19b",
        "name": "Tata Salt",
        "unit": "pkts",
        "basis_qty": 1.0,
        "basis_unit": "pkts",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹25.00 confirmed by stored evidence (0 purchases, 1 sales, MRP: None).",
    },
    "3aa05a8588b349c3ae3fe807d824def8": {
        "id": "3aa05a8588b349c3ae3fe807d824def8",
        "shop_id": "ec51853a955b4fe3b277afcad5ae59a9",
        "name": "Tata Salt 1kg",
        "unit": "pkt",
        "basis_qty": 1.0,
        "basis_unit": "pkt",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹28.00 confirmed by stored evidence (0 purchases, 2 sales, MRP: None).",
    },
    "49ee3c1d8d8f4ddb83d4165452241be4": {
        "id": "49ee3c1d8d8f4ddb83d4165452241be4",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Udad Dal 1 KG",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹52.00 confirmed by stored evidence (1 purchases, 0 sales, MRP: 60.0).",
    },
    "c57b1904b7bf4aadb27bc9463bcd47ff": {
        "id": "c57b1904b7bf4aadb27bc9463bcd47ff",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Udad Dal 1 KG",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹52.00 confirmed by stored evidence (1 purchases, 0 sales, MRP: 60.0).",
    },
    "171babc1dbd24bf1bd8ec49492adb486": {
        "id": "171babc1dbd24bf1bd8ec49492adb486",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "amul milk",
        "unit": "pkts",
        "basis_qty": 1.0,
        "basis_unit": "pkts",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹30.00 confirmed by stored evidence (0 purchases, 3 sales, MRP: None).",
    },
    "e1b291d1313547a5953d92e1e8d7ec3f": {
        "id": "e1b291d1313547a5953d92e1e8d7ec3f",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "milk",
        "unit": "pkts",
        "basis_qty": 1.0,
        "basis_unit": "pkts",
        "status": "VERIFIED",
        "evidence_tier": "Supported by invoice, sales, or manufacturer MRP evidence",
        "reason": "Active consumer product with valid price ₹28.00 confirmed by stored evidence (0 purchases, 1 sales, MRP: None).",
    },
    "24090a64eef34455a1d21f9861d18fe0": {
        "id": "24090a64eef34455a1d21f9861d18fe0",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Oil Can 10",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "WHOLESALE_ONLY",
        "evidence_tier": "Supported by invoice & stored pricing evidence",
        "reason": "Active commercial 10L sealed oil can procured and cataloged @ ₹2,150.00. Sold strictly as intact units.",
    },
    "c64c10b144a74a268fe4aeca1c783f17": {
        "id": "c64c10b144a74a268fe4aeca1c783f17",
        "shop_id": "62142ac63acb4816a0d531759d641d4c",
        "name": "Aashirvaad Atta",
        "unit": "bag",
        "basis_qty": 1.0,
        "basis_unit": "bag",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Catalog entry lacks empirical evidence (0 purchase invoice lines, 0 sales transactions, no manufacturer MRP). Positive price cannot be verified automatically.",
    },
    "a5d86f81cb424f6abf3aad02d7ef22c2": {
        "id": "a5d86f81cb424f6abf3aad02d7ef22c2",
        "shop_id": "62142ac63acb4816a0d531759d641d4c",
        "name": "Amul Butter 500g",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Catalog entry lacks empirical evidence (0 purchase invoice lines, 0 sales transactions, no manufacturer MRP). Positive price cannot be verified automatically.",
    },
    "87b9cb5001f84469b1988235da134cbf": {
        "id": "87b9cb5001f84469b1988235da134cbf",
        "shop_id": "62142ac63acb4816a0d531759d641d4c",
        "name": "Basmati Rice 5kg",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Title specifies '5kg' but physical unit is 'kg' with price ₹450.00. Risk of billing ₹450 for 1 kg.",
    },
    "02ec55379657459296572175fc16a1b4": {
        "id": "02ec55379657459296572175fc16a1b4",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Chana 50 KG",
        "unit": "bor",
        "basis_qty": 1.0,
        "basis_unit": "bor",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Commercial bulk sack @ ₹2,950.00. Ambiguity: Sold as unbroken wholesale sack or unpacked into loose kg retail stock.",
    },
    "14360e93a10044d195b601cbed622afe": {
        "id": "14360e93a10044d195b601cbed622afe",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Chana 50 KG",
        "unit": "bor",
        "basis_qty": 1.0,
        "basis_unit": "bor",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Commercial bulk sack @ ₹2,950.00. Ambiguity: Sold as unbroken wholesale sack or unpacked into loose kg retail stock.",
    },
    "81ab43d14f1e4b7ab31d82ac87b35cd5": {
        "id": "81ab43d14f1e4b7ab31d82ac87b35cd5",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Dettol Soap 125g",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Product is INACTIVE in catalog (is_active=0). Must not be enabled for active billing until manager verifies and reactivates.",
    },
    "483cedb8445c4f2a88cc3c5fd93c51ce": {
        "id": "483cedb8445c4f2a88cc3c5fd93c51ce",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Fortune Besan 500 GM",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Product is INACTIVE in catalog (is_active=0). Must not be enabled for active billing until manager verifies and reactivates.",
    },
    "32d1e614cf6e41869561dcaae8f372d5": {
        "id": "32d1e614cf6e41869561dcaae8f372d5",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Fortune Oil 1 KG",
        "unit": "pet",
        "basis_qty": 1.0,
        "basis_unit": "pet",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Title says '1 KG' but price is ₹1,520.00 with unit 'pet' (15L commercial tin). Severe unit/price mismatch.",
    },
    "f0a8c7e1770348ae95e29cce1b667662": {
        "id": "f0a8c7e1770348ae95e29cce1b667662",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Fortune Oil 1 KG",
        "unit": "pet",
        "basis_qty": 1.0,
        "basis_unit": "pet",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Title says '1 KG' but price is ₹1,520.00 with unit 'pet' (15L commercial tin). Severe unit/price mismatch.",
    },
    "9daddc26545c4862b720e352e09d6a63": {
        "id": "9daddc26545c4862b720e352e09d6a63",
        "shop_id": "7c9ed05d472c41e09bad8c2965392623",
        "name": "Fortune Sunflower Oil (1L)",
        "unit": "pouch",
        "basis_qty": 1.0,
        "basis_unit": "pouch",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Catalog entry lacks empirical evidence (0 purchase invoice lines, 0 sales transactions, no manufacturer MRP). Positive price cannot be verified automatically.",
    },
    "29caa1ae7dd24b9f87bd573af698937e": {
        "id": "29caa1ae7dd24b9f87bd573af698937e",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Hello Organic Chana Dal 1 KG",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Product is INACTIVE in catalog (is_active=0). Must not be enabled for active billing until manager verifies and reactivates.",
    },
    "2e365d3323b64537828e5b36c59dc35e": {
        "id": "2e365d3323b64537828e5b36c59dc35e",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Masoor Dal 1 kg",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Product is INACTIVE in catalog (is_active=0). Must not be enabled for active billing until manager verifies and reactivates.",
    },
    "59de739bb94543ba90fba6fc2895dd5d": {
        "id": "59de739bb94543ba90fba6fc2895dd5d",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Masoor Dal 50 KG",
        "unit": "bor",
        "basis_qty": 1.0,
        "basis_unit": "bor",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Commercial bulk sack @ ₹5,200.00. Ambiguity: Sold as unbroken wholesale sack or unpacked into loose kg retail stock.",
    },
    "6263a6960f0b42d08c11a73cdf2e22f9": {
        "id": "6263a6960f0b42d08c11a73cdf2e22f9",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Masoor Dal 50 KG",
        "unit": "bor",
        "basis_qty": 1.0,
        "basis_unit": "bor",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Commercial bulk sack @ ₹5,200.00. Ambiguity: Sold as unbroken wholesale sack or unpacked into loose kg retail stock.",
    },
    "052f4ed41faf479580416782440ad795": {
        "id": "052f4ed41faf479580416782440ad795",
        "shop_id": "bb833b1bb085454dbb0f38630fb8892d",
        "name": "Milk 500ml",
        "unit": "pkts",
        "basis_qty": 1.0,
        "basis_unit": "pkts",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Catalog entry lacks empirical evidence (0 purchase invoice lines, 0 sales transactions, no manufacturer MRP). Positive price cannot be verified automatically.",
    },
    "f53ff2a9dd6e451fb516127af2ef6f70": {
        "id": "f53ff2a9dd6e451fb516127af2ef6f70",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "New Product",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Placeholder / draft product title ('New Product'). Lacks genuine retail commercial identity.",
    },
    "c8553c3a0a99413795fff08b7dd86b74": {
        "id": "c8553c3a0a99413795fff08b7dd86b74",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Oil Can 10",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Product is INACTIVE in catalog (is_active=0). Must not be enabled for active billing until manager verifies and reactivates.",
    },
    "4b1285810a784d6b9e2e70e72a920a59": {
        "id": "4b1285810a784d6b9e2e70e72a920a59",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Parle-g",
        "unit": "pet",
        "basis_qty": 1.0,
        "basis_unit": "pet",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Unit 'pet' @ ₹700.00. Wholesale carton vs unpacked biscuit packet ambiguity.",
    },
    "a0b490a9da8245bab0ee49bc1894be80": {
        "id": "a0b490a9da8245bab0ee49bc1894be80",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Parle-g",
        "unit": "pet",
        "basis_qty": 1.0,
        "basis_unit": "pet",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Unit 'pet' @ ₹700.00. Wholesale carton vs unpacked biscuit packet ambiguity.",
    },
    "89f2c622182e40188fc3781ee4d679ee": {
        "id": "89f2c622182e40188fc3781ee4d679ee",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Sabudana 30 KG",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Bulk 30 kg sack priced at ₹1,450.00 with unit 'kg'. Extreme risk of billing ₹1,450 per 1 kg.",
    },
    "f409fc73106f457d993e8961770a06b9": {
        "id": "f409fc73106f457d993e8961770a06b9",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Sabudana 30 KG",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Bulk 30 kg sack priced at ₹1,450.00 with unit 'kg'. Extreme risk of billing ₹1,450 per 1 kg.",
    },
    "eec7c95ebf214a5bafb7f56c4ce43d80": {
        "id": "eec7c95ebf214a5bafb7f56c4ce43d80",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Sonal Sabudana Khichdi 500 GM",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Title specifies '500 GM' but physical unit is 'kg' @ ₹45.00. Ambiguity: ₹45 per 500g pack or per kg.",
    },
    "366c5851e9914d3cb62ff254cdf8f2e7": {
        "id": "366c5851e9914d3cb62ff254cdf8f2e7",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Sonal Sabudana Khichdi 500gm",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Title specifies '500 GM' but physical unit is 'kg' @ ₹45.00. Ambiguity: ₹45 per 500g pack or per kg.",
    },
    "079db1f64f7f411eb009d73ff4ba988e": {
        "id": "079db1f64f7f411eb009d73ff4ba988e",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Soyabean Chunks 15 KG",
        "unit": "bor",
        "basis_qty": 1.0,
        "basis_unit": "bor",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Commercial bulk sack @ ₹1,350.00. Ambiguity: Sold as unbroken wholesale sack or unpacked into loose kg retail stock.",
    },
    "478c9f5e9e024904a2ca54cf6a873ea3": {
        "id": "478c9f5e9e024904a2ca54cf6a873ea3",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Soyabean Chunks 15 KG",
        "unit": "bor",
        "basis_qty": 1.0,
        "basis_unit": "bor",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Commercial bulk sack @ ₹1,350.00. Ambiguity: Sold as unbroken wholesale sack or unpacked into loose kg retail stock.",
    },
    "134d6419cecf4e958fc1c7584eb322ac": {
        "id": "134d6419cecf4e958fc1c7584eb322ac",
        "shop_id": "832efd65ed984db397a9e84fa002c192",
        "name": "Sugar",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Unit 'pcs' with bulk 50 kg sack price ₹2,050.00. High risk of billing ₹2,050 for 1 retail piece.",
    },
    "d131e9d6a6c14faebfc5539a770eb635": {
        "id": "d131e9d6a6c14faebfc5539a770eb635",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Sugar",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Unit 'pcs' with bulk 50 kg sack price ₹2,050.00. High risk of billing ₹2,050 for 1 retail piece.",
    },
    "e5beb56a317a442eb72ca5b5683874d4": {
        "id": "e5beb56a317a442eb72ca5b5683874d4",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Sugar 1 kg",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Product is INACTIVE in catalog (is_active=0). Must not be enabled for active billing until manager verifies and reactivates.",
    },
    "772383d3a0ff4148b28233c643f80506": {
        "id": "772383d3a0ff4148b28233c643f80506",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Surf Excel 1 kg",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Product is INACTIVE in catalog (is_active=0). Must not be enabled for active billing until manager verifies and reactivates.",
    },
    "954d38e309324ff898dbd437f0966adf": {
        "id": "954d38e309324ff898dbd437f0966adf",
        "shop_id": "4a64692cd2de4a7abf3cc6ec2c1bfcbb",
        "name": "Surf Excel 1 kg",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Surf Excel 1 kg priced at ₹50.00 (far below manufacturer MRP ₹120-140). Outdated/erroneous price.",
    },
    "4e56eb0dcbec4a53a23a973828f0b2b2": {
        "id": "4e56eb0dcbec4a53a23a973828f0b2b2",
        "shop_id": "8790eea168c94c89ade5091a2fa76278",
        "name": "Tata Salt 1 kg",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Product is INACTIVE in catalog (is_active=0). Must not be enabled for active billing until manager verifies and reactivates.",
    },
    "0c64056b16774e6699d6266b019b8673": {
        "id": "0c64056b16774e6699d6266b019b8673",
        "shop_id": "6a313cc3ca6542a5a846f1530a9b248f",
        "name": "Tata Salt 1kg",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Catalog entry lacks empirical evidence (0 purchase invoice lines, 0 sales transactions, no manufacturer MRP). Positive price cannot be verified automatically.",
    },
    "620f488b70a349a8b958ef5349001ef8": {
        "id": "620f488b70a349a8b958ef5349001ef8",
        "shop_id": "4754977373974067b7c9a32e282e4f88",
        "name": "Tata Salt 1kg",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Catalog entry lacks empirical evidence (0 purchase invoice lines, 0 sales transactions, no manufacturer MRP). Positive price cannot be verified automatically.",
    },
    "89b6e6d8882b4852978fb33d5d862f1d": {
        "id": "89b6e6d8882b4852978fb33d5d862f1d",
        "shop_id": "62142ac63acb4816a0d531759d641d4c",
        "name": "Tata Salt 1kg",
        "unit": "pkt",
        "basis_qty": 1.0,
        "basis_unit": "pkt",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Catalog entry lacks empirical evidence (0 purchase invoice lines, 0 sales transactions, no manufacturer MRP). Positive price cannot be verified automatically.",
    },
    "a5d9333f18f9493885034ae4ca0d4426": {
        "id": "a5d9333f18f9493885034ae4ca0d4426",
        "shop_id": "7c9ed05d472c41e09bad8c2965392623",
        "name": "Tata Salt 1kg",
        "unit": "pkt",
        "basis_qty": 1.0,
        "basis_unit": "pkt",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Catalog entry lacks empirical evidence (0 purchase invoice lines, 0 sales transactions, no manufacturer MRP). Positive price cannot be verified automatically.",
    },
    "e61b7f6245af48d2a645d038b8111721": {
        "id": "e61b7f6245af48d2a645d038b8111721",
        "shop_id": "b77c11b598b74263844090ff745df6b8",
        "name": "Tata Salt 1kg",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Catalog entry lacks empirical evidence (0 purchase invoice lines, 0 sales transactions, no manufacturer MRP). Positive price cannot be verified automatically.",
    },
    "e6decf0c605b431fa28a69acfbcabab8": {
        "id": "e6decf0c605b431fa28a69acfbcabab8",
        "shop_id": "62142ac63acb4816a0d531759d641d4c",
        "name": "Tata Salt 200g",
        "unit": "pkt",
        "basis_qty": 1.0,
        "basis_unit": "pkt",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Catalog entry lacks empirical evidence (0 purchase invoice lines, 0 sales transactions, no manufacturer MRP). Positive price cannot be verified automatically.",
    },
    "94cb7e3dd9e54c5c948cec0755e2a369": {
        "id": "94cb7e3dd9e54c5c948cec0755e2a369",
        "shop_id": "62142ac63acb4816a0d531759d641d4c",
        "name": "Tata Salt 500g",
        "unit": "pkt",
        "basis_qty": 1.0,
        "basis_unit": "pkt",
        "status": "NEEDS_REVIEW",
        "evidence_tier": "Requires manager confirmation",
        "reason": "Catalog entry lacks empirical evidence (0 purchase invoice lines, 0 sales transactions, no manufacturer MRP). Positive price cannot be verified automatically.",
    },
    "267dede9cc804127a1e6877e79151070": {
        "id": "267dede9cc804127a1e6877e79151070",
        "shop_id": "4a64692cd2de4a7abf3cc6ec2c1bfcbb",
        "name": "Aashirvaad Atta 5 kg",
        "unit": "bag",
        "basis_qty": 1.0,
        "basis_unit": "bag",
        "status": "INCOMPLETE",
        "evidence_tier": "Directly supported by stored catalog evidence",
        "reason": "Stored selling price is ₹0.00 (zero/missing). Fails price validity; cannot be checked out.",
    },
    "3a0232efed6c4324b5a225896b7802a8": {
        "id": "3a0232efed6c4324b5a225896b7802a8",
        "shop_id": "4a64692cd2de4a7abf3cc6ec2c1bfcbb",
        "name": "Britannia Marie Gold 800 g",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "INCOMPLETE",
        "evidence_tier": "Directly supported by stored catalog evidence",
        "reason": "Stored selling price is ₹0.00 (zero/missing). Fails price validity; cannot be checked out.",
    },
    "6a21d3f8bdd44eaa976cabbd9b100efa": {
        "id": "6a21d3f8bdd44eaa976cabbd9b100efa",
        "shop_id": "4a64692cd2de4a7abf3cc6ec2c1bfcbb",
        "name": "Dettol Soap 125g",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "INCOMPLETE",
        "evidence_tier": "Directly supported by stored catalog evidence",
        "reason": "Stored selling price is ₹0.00 (zero/missing). Fails price validity; cannot be checked out.",
    },
    "4826a533834f48f5b9374ef136a3316b": {
        "id": "4826a533834f48f5b9374ef136a3316b",
        "shop_id": "4a64692cd2de4a7abf3cc6ec2c1bfcbb",
        "name": "Masoor Dal 1 kg",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "INCOMPLETE",
        "evidence_tier": "Directly supported by stored catalog evidence",
        "reason": "Stored selling price is ₹0.00 (zero/missing). Fails price validity; cannot be checked out.",
    },
    "169cc0900efd4ccba775c1cf05859729": {
        "id": "169cc0900efd4ccba775c1cf05859729",
        "shop_id": "4a64692cd2de4a7abf3cc6ec2c1bfcbb",
        "name": "Parle-G Biscuit 800 g",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "INCOMPLETE",
        "evidence_tier": "Directly supported by stored catalog evidence",
        "reason": "Stored selling price is ₹0.00 (zero/missing). Fails price validity; cannot be checked out.",
    },
    "76aa99d189404051a3051c6161e217b2": {
        "id": "76aa99d189404051a3051c6161e217b2",
        "shop_id": "4a64692cd2de4a7abf3cc6ec2c1bfcbb",
        "name": "Sugar 1 kg",
        "unit": "kg",
        "basis_qty": 1.0,
        "basis_unit": "kg",
        "status": "INCOMPLETE",
        "evidence_tier": "Directly supported by stored catalog evidence",
        "reason": "Stored selling price is ₹0.00 (zero/missing). Fails price validity; cannot be checked out.",
    },
    "e7b6abd2fb3046c6ba7cb03c3c705ebb": {
        "id": "e7b6abd2fb3046c6ba7cb03c3c705ebb",
        "shop_id": "4a64692cd2de4a7abf3cc6ec2c1bfcbb",
        "name": "Tata Salt 1 kg Fortune Sunflower Oil 1 L",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "INCOMPLETE",
        "evidence_tier": "Directly supported by stored catalog evidence",
        "reason": "Stored selling price is ₹0.00 (zero/missing). Fails price validity; cannot be checked out.",
    },
    "2afd988c259141a7bc1356dfb4341b2d": {
        "id": "2afd988c259141a7bc1356dfb4341b2d",
        "shop_id": "4a64692cd2de4a7abf3cc6ec2c1bfcbb",
        "name": "ot Colgate Toothpaste 200 g",
        "unit": "pcs",
        "basis_qty": 1.0,
        "basis_unit": "pcs",
        "status": "INCOMPLETE",
        "evidence_tier": "Directly supported by stored catalog evidence",
        "reason": "Stored selling price is ₹0.00 (zero/missing). Fails price validity; cannot be checked out.",
    },
}

def reconcile_product_classification(
    db: Session,
    audited_mapping: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    dry_run: bool = False,
) -> ReconciliationReport:
    """Reconcile product pricing basis and status against the verified audit mapping.

    Rules:
    1. Matches strictly by exact Product ID AND Shop ID.
    2. Never updates products using name alone.
    3. Preserves is_active, selling_price, purchase_price, mrp, and stock unchanged.
    4. Unmatched products remain untouched in NEEDS_REVIEW.
    5. Mismatched shop IDs are logged as conflicts and rejected.
    6. Idempotent: repeated runs produce identical state.
    7. Atomic: any unhandled error triggers db.rollback() so zero partial updates commit.
    """
    mapping = audited_mapping if audited_mapping is not None else AUDITED_65_PRODUCTS
    report = ReconciliationReport(total_audited=len(mapping), dry_run=dry_run)
    status_counts: Dict[str, int] = {"VERIFIED": 0, "NEEDS_REVIEW": 0, "INCOMPLETE": 0, "WHOLESALE_ONLY": 0}

    try:
        all_db_products = db.query(Product).all()
        db_by_id = {str(p.id).replace("-", "").lower(): p for p in all_db_products}

        for pid_str, expected in mapping.items():
            norm_pid = pid_str.replace("-", "").lower()
            product = db_by_id.get(norm_pid)

            if not product:
                report.unmatched_count += 1
                logger.warning("Audited product %s (%s) not found in database", pid_str, expected.get("name"))
                continue

            # Strict Shop Ownership Verification
            actual_shop_id = str(product.shop_id).replace("-", "").lower()
            expected_shop_id = expected["shop_id"].replace("-", "").lower()
            if actual_shop_id != expected_shop_id:
                report.conflict_count += 1
                conflict_info = {
                    "product_id": pid_str,
                    "name": expected["name"],
                    "actual_shop_id": actual_shop_id,
                    "expected_shop_id": expected_shop_id,
                    "reason": "Shop ownership mismatch",
                }
                report.conflicts.append(conflict_info)
                logger.error("Security conflict: product %s shop_id mismatch (%s != %s)", pid_str, actual_shop_id, expected_shop_id)
                continue

            # Apply additive classification fields
            st = expected["status"]
            status_counts[st] = status_counts.get(st, 0) + 1
            report.matched_count += 1

            if not dry_run:
                product.price_basis_quantity = expected["basis_qty"]
                product.price_basis_unit = expected["basis_unit"]
                product.pricing_status = st

        # Ensure any product in DB not present in audit mapping remains NEEDS_REVIEW
        for norm_pid, prod in db_by_id.items():
            if norm_pid not in mapping:
                # Product is unknown/unmatched
                if not dry_run and prod.pricing_status != "NEEDS_REVIEW":
                    prod.pricing_status = "NEEDS_REVIEW"
                status_counts["NEEDS_REVIEW"] = status_counts.get("NEEDS_REVIEW", 0) + 1

        if not dry_run:
            db.commit()

    except Exception as exc:
        if not dry_run:
            db.rollback()
        report.error = str(exc)
        logger.exception("Reconciliation failed and was rolled back: %s", exc)
        raise

    report.status_counts = status_counts
    return report
