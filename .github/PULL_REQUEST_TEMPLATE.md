## Summary

Describe the problem, the chosen approach, and the user-visible impact.

## Verification

- [ ] `python3 -m unittest discover -s tests -v`
- [ ] Contract validation CLI passes
- [ ] New or changed metrics exist in `examples/synthetic_data/metrics.json`
- [ ] New or changed Gold Cases are machine-validatable
- [ ] Documentation is updated when behavior or contracts change

## Safety boundary

- [ ] Uses synthetic data only
- [ ] Does not add production credentials, private schemas, or operational data
- [ ] Natural language still compiles to constrained `QueryIR`
- [ ] No free-form model SQL is executed
