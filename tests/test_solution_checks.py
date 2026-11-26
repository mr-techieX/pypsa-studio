from types import SimpleNamespace
import unittest

import xarray as xr

from energy_gui.solution_checks import check_solution


def array(value):
    return xr.DataArray([value], dims=["row"])


class SolutionCheckTests(unittest.TestCase):
    def model(self, value=2., lhs=2., sign="=", rhs=2., integer=False):
        variable = SimpleNamespace(solution=array(value), lower=array(0.), upper=array(3.), labels=array(0), attrs={"integer": integer})
        constraint = SimpleNamespace(lhs=SimpleNamespace(solution=array(lhs)), rhs=array(rhs), sign=array(sign), labels=array(0))
        return SimpleNamespace(variables={"power": variable}, constraints={"balance": constraint})

    def test_valid_solution_and_masked_coordinates(self):
        model = self.model()
        self.assertEqual(check_solution(model)["status"], "passed")
        model.constraints["balance"].labels = array(-1)
        model.constraints["balance"].lhs.solution = array(float("nan"))
        self.assertEqual(check_solution(model)["status"], "passed")

    def test_balance_and_inequality_violations_rejected(self):
        for model in [self.model(lhs=3), self.model(lhs=3, sign="<="), self.model(lhs=1, sign=">=")]:
            with self.assertRaises(ValueError):
                check_solution(model)

    def test_bounds_integrality_and_nonfinite_values_rejected(self):
        for model in [self.model(value=4), self.model(value=0.5, integer=True), self.model(value=float("nan"))]:
            with self.assertRaises(ValueError):
                check_solution(model)
