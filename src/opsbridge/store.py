"""Persistence backends for audit events, traces, tickets and approvals.

FileStore  (default): JSON-lines files under runs/ - identical behaviour to the first version, used by tests and the offline demo.
DynamoStore (OPSBRIDGE_STORE=dynamodb, OPSBRIDGE_TABLE=<name>): one DynamoDB table (pk = collection, sk = time#id). Approval decisions use a
conditional write, so two people (or two Lambda containers) cannot both decide the same approval: the second one fails.
Everything written here has already passed through redact() in the callers.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone

from . import config


class FileStore:
    name = "file"

    def append(self, collection: str, record: dict) -> None:
        with (config.runs_dir() / f"{collection}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def read(self, collection: str) -> list[dict]:
        p = config.runs_dir() / f"{collection}.jsonl"
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []

    # ---- approvals
    def _load(self) -> list[dict]:
        p = config.runs_dir() / "approvals.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

    def _save(self, items: list[dict]) -> None:
        (config.runs_dir() / "approvals.json").write_text(json.dumps(items, indent=1), encoding="utf-8")

    def approvals_all(self) -> list[dict]:
        return self._load()

    def approval_add(self, item: dict) -> None:
        items = self._load()
        items.append(item)
        self._save(items)

    def approval_get(self, approval_id: str) -> dict:
        for a in self._load():
            if a["id"] == approval_id:
                return a
        raise KeyError(approval_id)

    def approval_update(self, approval_id: str, **fields) -> dict:
        items = self._load()
        for a in items:
            if a["id"] == approval_id:
                a.update(fields)
                self._save(items)
                return a
        raise KeyError(approval_id)

    def approval_transition(self, approval_id: str, expect: str, new: str, **fields) -> dict:
        items = self._load()
        for a in items:
            if a["id"] == approval_id:
                if a["status"] != expect:
                    raise ValueError(f"approval {approval_id} is already {a['status']}")
                a.update(status=new, **fields)
                self._save(items)
                return a
        raise KeyError(approval_id)


class DynamoStore:
    name = "dynamodb"

    def __init__(self, table_name: str, region: str | None = None, resource=None):
        self.table_name = table_name
        if resource is None:
            import boto3  # lazy: the package works without AWS
            resource = boto3.resource("dynamodb", region_name=region or config.AWS_REGION)
        self.table = resource.Table(table_name)
        self.retention = int(os.environ.get("OPSBRIDGE_RETENTION_DAYS", "30")) * 86400

    def _ttl(self) -> int:
        return int(time.time()) + self.retention

    def append(self, collection: str, record: dict) -> None:
        sk = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%f')}#{uuid.uuid4().hex[:8]}"
        self.table.put_item(Item={"pk": collection, "sk": sk, "data": json.dumps(record), "ttl": self._ttl()})

    def read(self, collection: str) -> list[dict]:
        from boto3.dynamodb.conditions import Key
        out, kw = [], {"KeyConditionExpression": Key("pk").eq(collection)}
        while True:
            r = self.table.query(**kw)
            out += [json.loads(i["data"]) for i in r["Items"]]
            if "LastEvaluatedKey" not in r:
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    # ---- approvals (pk = "approvals", sk = approval id)
    def approvals_all(self) -> list[dict]:
        return self.read("approvals")

    def approval_add(self, item: dict) -> None:
        self.table.put_item(Item={"pk": "approvals", "sk": item["id"], "status": item["status"], "data": json.dumps(item), "ttl": self._ttl()},
                            ConditionExpression="attribute_not_exists(pk)")

    def approval_get(self, approval_id: str) -> dict:
        r = self.table.get_item(Key={"pk": "approvals", "sk": approval_id}, ConsistentRead=True)
        if "Item" not in r:
            raise KeyError(approval_id)
        return json.loads(r["Item"]["data"])

    def approval_update(self, approval_id: str, **fields) -> dict:
        a = self.approval_get(approval_id)
        a.update(fields)
        self.table.update_item(Key={"pk": "approvals", "sk": approval_id}, UpdateExpression="SET #d = :d, #s = :s",
                               ExpressionAttributeNames={"#d": "data", "#s": "status"},
                               ExpressionAttributeValues={":d": json.dumps(a), ":s": a["status"]})
        return a

    def approval_transition(self, approval_id: str, expect: str, new: str, **fields) -> dict:
        from botocore.exceptions import ClientError
        a = self.approval_get(approval_id)
        a.update(status=new, **fields)
        try:
            self.table.update_item(Key={"pk": "approvals", "sk": approval_id}, UpdateExpression="SET #d = :d, #s = :new",
                                   ConditionExpression="#s = :expect", ExpressionAttributeNames={"#d": "data", "#s": "status"},
                                   ExpressionAttributeValues={":d": json.dumps(a), ":new": new, ":expect": expect})
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(f"approval {approval_id} is already {self.approval_get(approval_id)['status']}") from exc
            raise
        return a


_file = FileStore()
_dynamo: dict[str, DynamoStore] = {}


def get_store():
    if os.environ.get("OPSBRIDGE_STORE", "file").lower() == "dynamodb":
        table = os.environ.get("OPSBRIDGE_TABLE")
        if not table:
            raise RuntimeError("OPSBRIDGE_STORE=dynamodb requires OPSBRIDGE_TABLE")
        if table not in _dynamo:
            _dynamo[table] = DynamoStore(table)
        return _dynamo[table]
    return _file


def reset_cache() -> None:
    """Forget cached cloud clients (used by tests that create/destroy mock tables)."""
    _dynamo.clear()
