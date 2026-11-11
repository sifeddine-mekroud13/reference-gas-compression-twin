# 0009. State estimator for twin synchronization: UKF, with a steady-state baseline

- Status: proposed (implemented in the twin milestone)
- Date: 2026-11-08

## Decision
Unscented Kalman Filter with the state augmented by random-walk degradation parameters
(head and efficiency fouling factors, cooler UA factor). Baseline it must beat: steady-state
detection plus recursive least squares on corrected KPIs, which is what industrial
performance monitoring does.

## Rationale
Property calls are black boxes (no analytic Jacobian), the state dimension is small (5 to 8,
so 11 to 17 sigma points), and the map nonlinearity near surge hurts EKF linearization.

## Guard against "inverse crime"
The estimator model must differ from the plant simulator: perturbed parameters, different
map fidelity, simpler thermo. Estimation error is reported against simulator ground truth.
