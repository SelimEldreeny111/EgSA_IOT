"""WIOT data-analysis and machine-learning pipeline.

Modules
-------
- :mod:`wiot.analytics.dataset`     read-only loaders and the shared command feature builder
- :mod:`wiot.analytics.descriptive` fleet/link, power, sensor and command analyses
- :mod:`wiot.analytics.energy`      battery-life model derived from POWER_DOWN_MODE_STUDY.md
- :mod:`wiot.analytics.repo_stats`  firmware footprint, power-guard verification, project size
- :mod:`wiot.analytics.modeling`    "Command Delivery Risk" training and evaluation
- :mod:`wiot.analytics.riskmodel`   serialisable fitted model + additive explanations
- :mod:`wiot.analytics.predictor`   serve-time loader used by the API (``CommandRiskPredictor``)
- :mod:`wiot.analytics.pipeline`    CLI: ``python -m wiot.analytics.pipeline --data-dir ... --out ...``

Heavy dependencies (scikit-learn, xgboost, lightgbm, shap, matplotlib) are imported
lazily inside the modules that need them, so importing this package is cheap.
"""
