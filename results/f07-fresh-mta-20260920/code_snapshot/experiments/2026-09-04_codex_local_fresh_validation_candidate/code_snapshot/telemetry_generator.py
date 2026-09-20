"""Physically grounded synthetic satellite telemetry generator.

12 channels driven by a circular low-Earth-orbit cycle (period P = 5700 s,
eclipse fraction f_e = 0.36), a two-state payload duty cycle, first-order
thermal lags, cross-channel electrical/thermal couplings, and AR(1) +
white sensor noise. Sampling interval dt = 30 s (190 samples per orbit).

Channels (index, name, unit):
 0 v_bus       bus voltage [V]            V = V0 + kv (SOC-0.8) - r max(0,-I_b) + e
 1 i_load      load current [A]           I_load = I0 + I_pl m(t) + e
 2 i_sa        solar-array current [A]    I_sa = I_max s(t) (1 + 0.02 sin 2pi t/P_y) + e
 3 i_batt      battery current [A]        I_b = I_sa - I_load, charge-tapered near SOC=1
 4 t_batt      battery temperature [C]    tau=2400 s, T_eq = 10 + 8 |I_b|/I_max
 5 t_sa        solar-array temp [C]       tau=480 s,  T_eq = -80 + 140 s(t)
 6 t_pl        payload temp [C]           tau=1500 s, T_eq = 5 + 20 m(t) + 5 s(t)
 7 t_obc       on-board computer temp [C] tau=1800 s, T_eq = 18 + 4 m(t) + 2 s(t)
 8 t_rad       radiator temp [C]          tau=900 s,  T_eq = -25 + 18 s(t) + 6 m(t)
 9 w_rwx       reaction wheel x [rad/s]   sinusoid at orbit period + sawtooth desat + AR(1)
10 w_rwy       reaction wheel y [rad/s]   idem (phase-shifted)
11 t_rwx       wheel-x bearing temp [C]   tau=1200 s, T_eq = 12 + 10 |w_x|/w_max

Anomaly taxonomy (type, primary channels eligible, severity 1-3):
 stuck    : sensor frozen at onset value;                     sev 1
 dropout  : intermittent samples fall to sensor floor;        sev 1
 bias     : additive step of 3-6 train-sigma;                 sev 2
 drift    : linear ramp reaching 3-8 sigma at event end;      sev 2
 coupling : physical component replaced by independent AR(1)
            with matched marginal moments (decorrelation);    sev 2
 runaway  : exponential thermal-runaway precursor on a temp
            channel + coupled current increase (secondary);   sev 3
"""
import numpy as np

DT = 30.0
P_ORBIT = 5700.0
N_PER_ORBIT = int(P_ORBIT / DT)  # 190
ECLIPSE_FRAC = 0.36
CH_NAMES = ["v_bus","i_load","i_sa","i_batt","t_batt","t_sa","t_pl","t_obc",
            "t_rad","w_rwx","w_rwy","t_rwx"]
NCH = 12
TEMP_CH = [4,5,6,7,8,11]
SENSOR_FLOOR = {0:0.0,1:0.0,2:0.0,3:0.0,4:-50.,5:-120.,6:-50.,7:-50.,8:-60.,9:0.,10:0.,11:-50.}

ANOM_TYPES = ["stuck","dropout","bias","drift","coupling","runaway"]
SEVERITY = {"stuck":1,"dropout":1,"bias":2,"drift":2,"coupling":2,"runaway":3}
ELIGIBLE = {"stuck": list(range(12)), "dropout": list(range(12)),
            "bias": list(range(12)), "drift": [0,2,3,4,5,6,7,8,11],
            "coupling": [2,3,5,6,8,11], "runaway": [4,6,11]}
RUNAWAY_SECONDARY = {4:3, 6:1, 11:9}  # coupled current/speed channel
DUR = {"stuck":(20,80),"dropout":(10,40),"bias":(30,100),"drift":(80,200),
       "coupling":(60,150),"runaway":(60,120)}

def _ar1(rng, n, phi, sig):
    x = np.zeros(n); e = rng.normal(0, sig, n)
    for i in range(1, n):
        x[i] = phi * x[i-1] + e[i]
    return x

def generate_nominal(n_orbits, rng):
    n = n_orbits * N_PER_ORBIT
    t = np.arange(n) * DT
    phase = (t % P_ORBIT) / P_ORBIT
    # illumination with 1-sample penumbra ramps
    s = np.clip((phase - ECLIPSE_FRAC) / 0.005, 0, 1) * (phase >= ECLIPSE_FRAC)
    s = np.where(phase < ECLIPSE_FRAC, 0.0, np.minimum(1.0, (phase - ECLIPSE_FRAC) / 0.01))
    # payload mode: geometric dwell, mean 3 orbits
    m = np.zeros(n); state = rng.integers(0, 2); i = 0
    while i < n:
        dwell = int(rng.exponential(3.0 * N_PER_ORBIT)) + N_PER_ORBIT // 2
        m[i:i+dwell] = state; state = 1 - state; i += dwell
    I_max, I0, I_pl = 8.0, 3.0, 2.5
    i_load = I0 + I_pl * m + _ar1(rng, n, 0.9, 0.03)
    i_sa = I_max * s * (1 + 0.02 * np.sin(2*np.pi*t/(365.25*86400/8))) + _ar1(rng, n, 0.8, 0.05) * s
    # SOC integration with charge taper
    soc = np.zeros(n); soc[0] = 0.85; Q = 40.0 * 3600; eta = 0.95
    i_b = np.zeros(n)
    for k in range(n):
        ib = i_sa[k] - i_load[k]
        if ib > 0 and soc[k-1 if k else 0] > 0.97:
            ib *= max(0.0, (1.0 - soc[k-1 if k else 0]) / 0.03)
        i_b[k] = ib
        if k < n-1:
            soc[k+1] = np.clip(soc[k] + eta * ib * DT / Q, 0.55, 1.0)
    v_bus = 28.0 + 6.0*(soc-0.8) - 0.08*np.maximum(0,-i_b)
    # reaction wheels
    w0 = 150.0; w_max = 300.0
    saw = ((t / (5*P_ORBIT)) % 1.0)
    w_rwx = w0 + 60*np.sin(2*np.pi*t/P_ORBIT) + 40*(saw-0.5) + _ar1(rng,n,0.95,1.0)
    w_rwy = w0 + 55*np.sin(2*np.pi*t/P_ORBIT + 1.9) + 40*(saw-0.5) + _ar1(rng,n,0.95,1.0)
    # first-order thermal lags
    def lag(T_eq, tau, T0):
        T = np.zeros(n); T[0] = T0; a = DT / tau
        for k in range(n-1):
            T[k+1] = T[k] + a * (T_eq[k] - T[k])
        return T
    t_batt = lag(10 + 8*np.abs(i_b)/I_max, 2400, 12.)
    t_sa   = lag(-80 + 140*s, 480, 20.)
    t_pl   = lag(5 + 20*m + 5*s, 1500, 15.)
    t_obc  = lag(18 + 4*m + 2*s, 1800, 20.)
    t_rad  = lag(-25 + 18*s + 6*m, 900, -15.)
    t_rwx  = lag(12 + 10*np.abs(w_rwx)/w_max, 1200, 17.)
    X = np.stack([v_bus, i_load, i_sa, i_b, t_batt, t_sa, t_pl, t_obc,
                  t_rad, w_rwx, w_rwy, t_rwx], axis=1)
    # measurement noise: 1% of per-channel dynamic range
    rng_meas = np.std(X, axis=0)
    X = X + rng.normal(0, 0.01, X.shape) * (np.maximum(rng_meas, 1e-3) * 1.0)
    X = X + rng.normal(0, 0.005, X.shape) * np.maximum(np.abs(X).mean(0), 1e-3)
    return X, m, s

def inject_anomalies(X, m, rng, n_per_type=6, sigma=None, gap=40):
    n = X.shape[0]
    Xa = X.copy(); lab = np.zeros(n, dtype=int)
    if sigma is None:
        sigma = X.std(axis=0)
    events = []; occupied = np.zeros(n, dtype=bool)
    order = [t for t in ANOM_TYPES for _ in range(n_per_type)]
    rng.shuffle(order)
    for typ in order:
        d = rng.integers(*DUR[typ])
        for _ in range(300):
            st = rng.integers(N_PER_ORBIT, n - d - N_PER_ORBIT)
            if not occupied[max(0,st-gap):st+d+gap].any():
                break
        else:
            continue
        en = st + d
        ch = int(rng.choice(ELIGIBLE[typ])); sec = -1
        if typ == "stuck":
            Xa[st:en, ch] = Xa[st, ch]
        elif typ == "dropout":
            idx = st + np.where(rng.random(d) < 0.6)[0]
            Xa[idx, ch] = SENSOR_FLOOR[ch]
        elif typ == "bias":
            Xa[st:en, ch] += rng.choice([-1,1]) * rng.uniform(3,6) * sigma[ch]
        elif typ == "drift":
            g = rng.choice([-1,1]) * rng.uniform(3,8) * sigma[ch]
            Xa[st:en, ch] += g * np.linspace(0, 1, d)
        elif typ == "coupling":
            mu = X[st:en, ch].mean(); sd = X[st:en, ch].std() + 1e-6
            z = _ar1(rng, d, 0.97, 1.0); z = (z - z.mean()) / (z.std()+1e-9)
            Xa[st:en, ch] = mu + sd * z
        elif typ == "runaway":
            sec = RUNAWAY_SECONDARY[ch]
            tau_r = d / 3.0
            rise = (np.exp(np.arange(d)/tau_r) - 1)
            rise = rise / rise[-1]
            Xa[st:en, ch] += rng.uniform(4,8) * sigma[ch] * rise
            Xa[st:en, sec] += rng.uniform(2,4) * sigma[sec] * rise
        occupied[st:en] = True; lab[st:en] = 1
        events.append(dict(type=typ, ch=ch, sec=sec, start=int(st), end=int(en),
                           sev=SEVERITY[typ], mode=int(m[st])))
    return Xa, lab, events

def generate_seed(seed, out_path):
    rng = np.random.default_rng(seed)
    Xtr, mtr, _ = generate_nominal(60, rng)
    Xval, mval, _ = generate_nominal(30, rng)
    sig = Xtr.std(axis=0)
    Xtl_nom, mtl, _ = generate_nominal(130, rng)
    Xtl, ytl, ev_tl = inject_anomalies(Xtl_nom, mtl, rng, n_per_type=6, sigma=sig)
    Xte_nom, mte, _ = generate_nominal(130, rng)
    Xte, yte, ev_te = inject_anomalies(Xte_nom, mte, rng, n_per_type=6, sigma=sig)
    import json
    np.savez_compressed(out_path,
        Xtr=Xtr.astype(np.float32), Xval=Xval.astype(np.float32),
        Xtl=Xtl.astype(np.float32), ytl=ytl, Xte=Xte.astype(np.float32), yte=yte,
        mtr=mtr, mte=mte, ev_tl=json.dumps(ev_tl), ev_te=json.dumps(ev_te))

if __name__ == "__main__":
    import sys
    seed = int(sys.argv[1])
    generate_seed(seed, f"../data/telemetry_seed{seed}.npz")
    print("OK seed", seed)
