// =====================================================================
//  params.sce  -  SINGLE SOURCE OF TRUTH for the AVR-25D payload
//  PRD.md §16 companion workstream.  Owner: Khanak.
//
//  Every other script starts with:   exec("params.sce", -1);
//  Change a number HERE and every figure and table downstream changes.
//  That is what makes HW-8 ("every figure reproducible") true.
//
//  PROVENANCE TAGS
//    [PRD]   stated in PRD.md (section given)
//    [CFG]   from avr25d/config.yaml, therefore PS-traceable
//    [DER]   derived from a [PRD] or [CFG] value, derivation shown
//    [ASM]   our engineering assumption, defended in DESIGN_REPORT.md
//    [CND]   candidate component spec, confirm against datasheet
// =====================================================================

// ---- physical constants (SI definitions, exact) ----------------------
C_LIGHT = 299792458.0;      // [m/s]
Q_E     = 1.602176634e-19;  // [C]
K_B     = 1.380649e-23;     // [J/K]

// ---- mission envelope -------------------------------------------------
R_MAX_REQ = 100.0;   // [CFG] grid.r_max  = 100 m  (PS-6)
R_KNEE    = 10.0;    // [CFG] grid.r_knee = 10 m   (PS-6)
S_MIN     = 0.05;    // [CFG] grid.s_min  = 0.05 m at r <= r_knee (PS-6)
S_MAX     = 0.50;    // [CFG] grid.s_max  = 0.50 m at r_max       (PS-6)

// [DER] PS-6 asks for 5 cm cells at 10 m and 50 cm cells at 100 m.
//       0.05/10 = 0.005 rad and 0.50/100 = 0.005 rad.  Both ends give the
//       SAME angle.  PS-6's variable-resolution law IS a constant angular
//       pitch, which is exactly what a scanning LiDAR produces natively.
ANG_PITCH = 0.005;   // [DER] required angular sampling pitch  [rad]

// ---- emitter ----------------------------------------------------------
LAMBDA     = 905e-9;  // [PRD §16.1] 905 nm pulsed laser diode
PULSE_FWHM = 5.0e-9;  // [ASM] pulse width  [s]
P_PEAK     = 3.8;     // [DER] peak optical power [W]. NOT a free choice:
                      //       it is the Class 1 cap computed by
                      //       eye_safety.sce for D_TX = 50 mm. Do not
                      //       raise it without re-running eye_safety.sce.
PRF        = 200e3;   // [DER] pulse repetition frequency [Hz], set by
                      //       scan_coverage.sce from FOV, pitch, N_ACC
N_ACC      = 4;       // [ASM] pulses accumulated per beam direction
T_I_GROUP  = 5.0e-6;  // [PRD-ext] IEC 60825-1 thermal grouping window Ti
                      //       for 700-1050 nm. Accumulation pulses are
                      //       spaced by Ti so they are NOT thermally
                      //       grouped in the eye-safety analysis.

// ---- transmit optics --------------------------------------------------
D_TX      = 0.050;    // [ASM] exit aperture diameter [m], drives eye safety
DIV_TX    = 0.005;    // [DER] beam divergence [rad], matched to ANG_PITCH
                      //       so the spot fills one cell with no gaps

// ---- channel ----------------------------------------------------------
RHO_MIN   = 0.1;      // [PRD HW-1] reflectivity band lower bound
RHO_MAX   = 0.9;      // [PRD HW-1] reflectivity band upper bound
RHO_NOM   = 0.1;      // [ASM] worst case used for all sizing
ALPHA_ATM = 0.2e-3;   // [ASM] atmospheric extinction [1/m], clear air

// ---- receive optics ---------------------------------------------------
D_RX      = 0.050;    // [ASM] receiver aperture diameter [m]
ETA_OPT   = 0.80;     // [ASM] optical transmission efficiency
FILTER_BW = 20.0;     // [ASM] 905 nm bandpass filter width [nm]
THETA_RX  = 0.005;    // [DER] receiver IFOV [rad], matched to ANG_PITCH
E_SUN     = 0.6;      // [ASM] solar spectral irradiance at 905 nm
                      //       [W/(m^2*nm)], clear day

// ---- detector (APD) ---------------------------------------------------
R_LAMBDA = 0.50;      // [CND] APD responsivity at unity gain [A/W]
M_APD    = 100.0;     // [CND] APD multiplication factor [-]  (PRD HW-3)
K_EFF    = 0.02;      // [CND] silicon ionisation ratio [-]
I_DARK   = 1.0e-9;    // [CND] bulk dark current, pre-gain [A]

// ---- TIA --------------------------------------------------------------
F_3DB    = 200e6;     // [PRD §16.1] "~200 MHz" TIA bandwidth
R_F      = 1.0e3;     // [ASM] transimpedance gain [V/A]
I_N_TIA  = 3.0e-12;   // [CND] input current noise density [A/sqrt(Hz)]
T_KELVIN = 300.0;     // [ASM] operating temperature [K]
V_SAT    = 2.0;       // [ASM] TIA output saturation [V]

// ---- discriminator and TDC --------------------------------------------
CFD_FRACTION = 0.70;   // [DER] constant-fraction attenuation. Swept in
                       //       rx_chain.sce: 0.7 with a 4 ns delay puts the
                       //       zero crossing on the STEEP part of the edge,
                       //       not near the flat peak. Worst-case total
                       //       range error falls from 32 cm to 5 cm.
CFD_DELAY    = 4.0e-9; // [DER] constant-fraction delay [s], same sweep
TDC_LSB      = 50e-12; // [PRD §16.1] "~50 ps LSB"
N_SIGMA_THR  = 5.0;    // [ASM] fixed threshold in sigma at R_MAX_REQ

// ---- scan -------------------------------------------------------------
FOV_AZ_DEG = 30.0;    // [ASM] azimuth field of view [deg]
FOV_EL_DEG = 20.0;    // [ASM] elevation field of view [deg]

// ---- platform ---------------------------------------------------------
MASS_LIMIT_G  = 1500.0; // [PLAN] drone payload mass limit [g]. WORK_DISTRIBUTION
                        //       6.1 Day 11 states "mass < 1.5 kg". Earlier
                        //       drafts of this file used 500 g; the team
                        //       figure governs.
POWER_LIMIT_W = 25.0;   // [PLAN] drone payload power limit [W], same source

// ---- detection criterion ----------------------------------------------
SNR_THRESH = 6.0;     // [ASM] SNR needed to declare a valid return

// ---- simulation control -----------------------------------------------
DT_SIM   = 50e-12;    // [ASM] receiver-chain time step [s]
N_SAMP   = 16384;     // [ASM] samples per simulated shot
RNG_SEED = 12345;     // [ASM] random seed for repeatability

// =====================================================================
//  DERIVED QUANTITIES
// =====================================================================
A_RX      = %pi * D_RX^2 / 4;
A_TX      = %pi * D_TX^2 / 4;
PULSE_SIG = PULSE_FWHM / 2.35482;
TAU_DET   = 1 / (2*%pi*F_3DB);
ENB       = 1.57 * F_3DB;
F_EXCESS  = K_EFF*M_APD + (2 - 1/M_APD)*(1 - K_EFF);
E_PULSE   = P_PEAK * PULSE_FWHM;
P_AVG_OPT = E_PULSE * PRF;
P_BG      = RHO_NOM * E_SUN * FILTER_BW * THETA_RX^2 * A_RX * ETA_OPT / 4;
SIGMA_TH  = R_F * sqrt(I_N_TIA^2*ENB + 4*K_B*T_KELVIN*ENB/R_F);

// =====================================================================
//  SHARED FUNCTIONS
// =====================================================================

// LiDAR range equation, diffuse target larger than the beam spot,
// normal incidence:  P_rx = P_tx*rho*A_rx/(pi R^2)*eta*exp(-2 alpha R)
function P = p_received(R, rho, P_tx, A_rx, eta, alpha)
    P = P_tx .* rho .* (A_rx ./ (%pi .* R.^2)) .* eta .* exp(-2 .* alpha .* R);
endfunction

// Amplitude SNR = peak signal voltage / rms noise voltage, after
// accumulating n_acc pulses (averaging grows SNR as sqrt(n_acc)).
function s = snr_of(R, rho, n_acc, P_tx, A_rx, eta, alpha, R_lam, M, F, ..
                    B, R_f, i_n, T, k_b, q_e, I_d, P_bg)
    P  = p_received(R, rho, P_tx, A_rx, eta, alpha);
    I  = R_lam .* P;
    Vp = R_f * M .* I * 0.98;
    v2 = (R_f*M)^2 .* 2*q_e .* (I + R_lam*P_bg + I_d) .* F .* B ..
         + R_f^2 * (i_n^2*B + 4*k_b*T*B/R_f);
    s  = Vp ./ sqrt(v2) .* sqrt(n_acc);
endfunction

// Linear convolution via FFT. Hd = FFT of the zero-padded impulse
// response, already scaled by dt.
function y = conv_h(x, Hd, N)
    X = fft([x, zeros(1,N)], -1);
    y = real(fft(X .* Hd, 1));
    y = y(1:N);
endfunction

// First upward crossing of a level, linearly interpolated. Sample i sits
// at time (i-1)*dt because Scilab indexes from 1.
function tc = xing_up(y, thr, i0, dt)
    tc = %nan;  n = length(y);
    if i0 < 1 then i0 = 1; end
    if i0 > n-1 then return; end
    k = find((y(i0:n-1) < thr) & (y(i0+1:n) >= thr));
    if isempty(k) then return; end
    i = k(1) + i0 - 1;  d = y(i+1) - y(i);
    if d == 0 then tc = (i-1)*dt; else tc = ((i-1) + (thr-y(i))/d)*dt; end
endfunction

// First downward crossing of zero, linearly interpolated.
function tc = xing_dn(y, i0, dt)
    tc = %nan;  n = length(y);
    if i0 < 1 then i0 = 1; end
    if i0 > n-1 then return; end
    k = find((y(i0:n-1) > 0) & (y(i0+1:n) <= 0));
    if isempty(k) then return; end
    i = k(1) + i0 - 1;  d = y(i+1) - y(i);
    if d == 0 then tc = (i-1)*dt; else tc = ((i-1) + (0-y(i))/d)*dt; end
endfunction

// Constant-fraction signal: f*v(t) - v(t - delay)
function vc = cfd_signal(v, frac, nd)
    n = length(v);
    vc = frac*v - [zeros(1,nd), v(1:n-nd)];
endfunction

// Create the shared output folders if they are missing.
function ensure_dirs()
    if ~isdir("../figures") then mkdir("../figures"); end
    if ~isdir("../figures/svg") then mkdir("../figures/svg"); end
    if ~isdir("../results") then mkdir("../results"); end
endfunction
