import sys, types, json, datetime as dt, unittest
from unittest import mock
sys.modules['boto3'] = types.SimpleNamespace(client=lambda *_a, **_k: mock.MagicMock())
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import handler as h

def ev(body, token="t"): return {"headers": {"X-Scale-Token": token}, "body": json.dumps(body)}
CTX = types.SimpleNamespace(aws_request_id="r1")

class T(unittest.TestCase):
    def setUp(self):
        h._secret = lambda name: {"TOKEN_SECRET_ARN": "t"}.get(name)
        h.asg = mock.MagicMock(); h.lmb = mock.MagicMock()
        h.asg.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": [
            {"AutoScalingGroupName": n, "MinSize": 2, "DesiredCapacity": 4, "MaxSize": 20} for n in h.ASG_NAMES.values()]}
        h.lmb.get_function_concurrency.return_value = {"ReservedConcurrentExecutions": 200}
        h._now_vn = lambda: dt.datetime(2026, 12, 1, 10, 0, tzinfo=h.VN)   # ngoài giờ thi
        h._scalar = lambda expr: 0.0                                        # DB OK

    def test_bad_token(self):
        self.assertEqual(h.handler(ev({"target": "asg", "preset": "60k"}, "x"), CTX)["statusCode"], 401)
    def test_bad_preset(self):
        self.assertEqual(h.handler(ev({"target": "asg", "preset": "999"}), CTX)["statusCode"], 400)
    def test_asg_scale_up_applies(self):
        r = h.handler(ev({"target": "asg", "preset": "60k", "user": "sre"}), CTX)
        self.assertEqual(r["statusCode"], 200, r)
        calls = h.asg.update_auto_scaling_group.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertIn(mock.call(AutoScalingGroupName=h.ASG_NAMES["api"], MinSize=40, MaxSize=70, DesiredCapacity=40), calls)
    def test_asg_blocked_when_gate_locked(self):
        h._scalar = lambda expr: 1.0
        r = h.handler(ev({"target": "asg", "preset": "60k"}), CTX)
        self.assertEqual(r["statusCode"], 409); h.asg.update_auto_scaling_group.assert_not_called()
    def test_asg_scale_down_blocked_in_exam_window(self):
        h._now_vn = lambda: dt.datetime(2026, 12, 1, 20, 0, tzinfo=h.VN)
        h.asg.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": [
            {"AutoScalingGroupName": n, "MinSize": 40, "DesiredCapacity": 40, "MaxSize": 70} for n in h.ASG_NAMES.values()]}
        r = h.handler(ev({"target": "asg", "preset": "standby"}), CTX)
        self.assertEqual(r["statusCode"], 409); self.assertIn("giờ thi", json.loads(r["body"])["reason"])
    def test_prom_missing_fails_closed(self):
        h._scalar = lambda expr: (_ for _ in ()).throw(h.Rejected("no prom"))
        r = h.handler(ev({"target": "lambda", "preset": "60k"}), CTX)
        self.assertEqual(r["statusCode"], 409); h.lmb.put_function_concurrency.assert_not_called()
    def test_lambda_apply_and_cap(self):
        r = h.handler(ev({"target": "lambda", "preset": "60k"}), CTX)
        self.assertEqual(r["statusCode"], 200)
        h.lmb.put_function_concurrency.assert_any_call(FunctionName="examination-lambda", ReservedConcurrentExecutions=3000)
        h.PRESETS["60k"]["lambda"]["examination-lambda"] = 3500
        try:
            self.assertEqual(h.handler(ev({"target": "lambda", "preset": "60k"}), CTX)["statusCode"], 409)
        finally:
            h.PRESETS["60k"]["lambda"]["examination-lambda"] = 3000
    def test_dry_run_no_writes(self):
        r = h.handler(ev({"target": "asg", "preset": "60k", "dry_run": True}), CTX)
        self.assertEqual(r["statusCode"], 200); h.asg.update_auto_scaling_group.assert_not_called()
    def test_atlas_blocked_in_exam_window(self):
        h._now_vn = lambda: dt.datetime(2026, 12, 1, 16, 0, tzinfo=h.VN)
        h._atlas = lambda m, p, b=None: {"stateName": "IDLE", "replicationSpecs": [{"regionConfigs": [{"electableSpecs": {"instanceSize": "M40", "nodeCount": 3}}]}]}
        r = h.handler(ev({"target": "atlas", "preset": "60k"}), CTX)
        self.assertEqual(r["statusCode"], 409); self.assertIn("29/10", json.loads(r["body"])["reason"])
    def test_atlas_upgrade_outside_window(self):
        sent = []
        def fake(m, p, b=None):
            if m == "PATCH": sent.append(b); return {}
            return {"stateName": "IDLE", "replicationSpecs": [{"regionConfigs": [{"electableSpecs": {"instanceSize": "M40", "nodeCount": 3}}]}]}
        h._atlas = fake
        r = h.handler(ev({"target": "atlas", "preset": "60k"}), CTX)
        self.assertEqual(r["statusCode"], 200, r)
        self.assertEqual(sent[0]["replicationSpecs"][0]["regionConfigs"][0]["electableSpecs"]["instanceSize"], "M60")
    def test_atlas_not_idle(self):
        h._atlas = lambda m, p, b=None: {"stateName": "UPDATING", "replicationSpecs": [{"regionConfigs": [{"electableSpecs": {"instanceSize": "M40", "nodeCount": 3}}]}]}
        self.assertEqual(h.handler(ev({"target": "atlas", "preset": "60k"}), CTX)["statusCode"], 409)

unittest.main(argv=["x", "-v"])
