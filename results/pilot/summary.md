# runs/pilot

## per model x tier

| model | tier | n | submitted | invalid_sections | mech_params | rules_ok | glossary | heldout_full | node_f1 | edge_f1 | roots | decoys_in | lots_f1 | timeline_f1 | offsets | claims_f1 | aggregate | solved_all | brier | tool_calls | cost_usd | end_reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| astra | default | 3 | 3/3 | 0/3 | 97/99 | 1/3 | 58/59 | 135/135 | 0.337 | 0.208 | 3/26 | 9/15 | 0.974 | 0.175 | 28/30 | 0.261 | 0.680 [0.656,0.713] | 0/3 | 0.439 | 41 (41-43) | 6.40 (sum 18.67) | {'stopped': 3} |
| sol | default | 3 | 3/3 | 0/3 | 83/99 | 0/3 | 57/59 | 135/135 | 0.596 | 0.364 | 5/26 | 0/15 | 0.948 | 0.598 | 23/30 | 0.201 | 0.745 [0.737,0.759] | 0/3 | 0.522 | 87 (74-92) | 1.99 (sum 6.60) | {'stopped': 3} |

## per run

```
[
 {
  "run": "runs/pilot/astra/s0001_90205ed8",
  "model": "astra",
  "end_reason": "stopped",
  "tool_calls": 43,
  "cost_usd": 6.702249,
  "invalid_markers": [],
  "aggregate": 0.655635664,
  "sections": {
   "mechanism": 0.983,
   "notation": 1.0,
   "causal_chain": 0.343,
   "timeline": 0.297
  },
  "solved": {
   "mechanism": false,
   "notation": true,
   "causal_chain": false,
   "timeline": false
  },
  "confidence": {
   "mechanism": {
    "confidence": 0.87,
    "solved": false,
    "sq_err": 0.7569
   },
   "notation": {
    "confidence": 0.98,
    "solved": true,
    "sq_err": 0.0004000000000000007
   },
   "causal_chain": {
    "confidence": 0.84,
    "solved": false,
    "sq_err": 0.7055999999999999
   },
   "timeline": {
    "confidence": 0.76,
    "solved": false,
    "sq_err": 0.5776
   }
  }
 },
 {
  "run": "runs/pilot/astra/s0002_2565130a",
  "model": "astra",
  "end_reason": "stopped",
  "tool_calls": 41,
  "cost_usd": 5.574184,
  "invalid_markers": [],
  "aggregate": 0.670292132,
  "sections": {
   "mechanism": 0.997,
   "notation": 0.979,
   "causal_chain": 0.406,
   "timeline": 0.3
  },
  "solved": {
   "mechanism": false,
   "notation": true,
   "causal_chain": false,
   "timeline": false
  },
  "confidence": {
   "mechanism": {
    "confidence": 0.87,
    "solved": false,
    "sq_err": 0.7569
   },
   "notation": {
    "confidence": 0.99,
    "solved": true,
    "sq_err": 0.00010000000000000018
   },
   "causal_chain": {
    "confidence": 0.86,
    "solved": false,
    "sq_err": 0.7395999999999999
   },
   "timeline": {
    "confidence": 0.83,
    "solved": false,
    "sq_err": 0.6889
   }
  }
 },
 {
  "run": "runs/pilot/astra/s0003_64ecd07a",
  "model": "astra",
  "end_reason": "stopped",
  "tool_calls": 41,
  "cost_usd": 6.398522,
  "invalid_markers": [],
  "aggregate": 0.713046929,
  "sections": {
   "mechanism": 0.986,
   "notation": 1.0,
   "causal_chain": 0.432,
   "timeline": 0.434
  },
  "solved": {
   "mechanism": true,
   "notation": true,
   "causal_chain": false,
   "timeline": false
  },
  "confidence": {
   "mechanism": {
    "confidence": 0.83,
    "solved": true,
    "sq_err": 0.028900000000000012
   },
   "notation": {
    "confidence": 0.98,
    "solved": true,
    "sq_err": 0.0004000000000000007
   },
   "causal_chain": {
    "confidence": 0.72,
    "solved": false,
    "sq_err": 0.5184
   },
   "timeline": {
    "confidence": 0.7,
    "solved": false,
    "sq_err": 0.48999999999999994
   }
  }
 },
 {
  "run": "runs/pilot/sol/s0001_90205ed8",
  "model": "sol",
  "end_reason": "stopped",
  "tool_calls": 92,
  "cost_usd": 1.98733,
  "invalid_markers": [],
  "aggregate": 0.739587306,
  "sections": {
   "mechanism": 0.941,
   "notation": 1.0,
   "causal_chain": 0.448,
   "timeline": 0.569
  },
  "solved": {
   "mechanism": false,
   "notation": true,
   "causal_chain": false,
   "timeline": false
  },
  "confidence": {
   "mechanism": {
    "confidence": 0.88,
    "solved": false,
    "sq_err": 0.7744
   },
   "notation": {
    "confidence": 0.94,
    "solved": true,
    "sq_err": 0.0036000000000000064
   },
   "causal_chain": {
    "confidence": 0.85,
    "solved": false,
    "sq_err": 0.7224999999999999
   },
   "timeline": {
    "confidence": 0.82,
    "solved": false,
    "sq_err": 0.6723999999999999
   }
  }
 },
 {
  "run": "runs/pilot/sol/s0002_2565130a",
  "model": "sol",
  "end_reason": "stopped",
  "tool_calls": 87,
  "cost_usd": 1.843189,
  "invalid_markers": [],
  "aggregate": 0.73724017,
  "sections": {
   "mechanism": 0.927,
   "notation": 0.979,
   "causal_chain": 0.542,
   "timeline": 0.501
  },
  "solved": {
   "mechanism": false,
   "notation": true,
   "causal_chain": false,
   "timeline": false
  },
  "confidence": {
   "mechanism": {
    "confidence": 0.8,
    "solved": false,
    "sq_err": 0.6400000000000001
   },
   "notation": {
    "confidence": 0.97,
    "solved": true,
    "sq_err": 0.0009000000000000016
   },
   "causal_chain": {
    "confidence": 0.91,
    "solved": false,
    "sq_err": 0.8281000000000001
   },
   "timeline": {
    "confidence": 0.82,
    "solved": false,
    "sq_err": 0.6723999999999999
   }
  }
 },
 {
  "run": "runs/pilot/sol/s0003_64ecd07a",
  "model": "sol",
  "end_reason": "stopped",
  "tool_calls": 74,
  "cost_usd": 2.764892,
  "invalid_markers": [],
  "aggregate": 0.758910985,
  "sections": {
   "mechanism": 0.844,
   "notation": 0.978,
   "causal_chain": 0.628,
   "timeline": 0.586
  },
  "solved": {
   "mechanism": false,
   "notation": true,
   "causal_chain": false,
   "timeline": false
  },
  "confidence": {
   "mechanism": {
    "confidence": 0.78,
    "solved": false,
    "sq_err": 0.6084
   },
   "notation": {
    "confidence": 0.94,
    "solved": true,
    "sq_err": 0.0036000000000000064
   },
   "causal_chain": {
    "confidence": 0.87,
    "solved": false,
    "sq_err": 0.7569
   },
   "timeline": {
    "confidence": 0.76,
    "solved": false,
    "sq_err": 0.5776
   }
  }
 }
]
```
