// =====================================================================
//  eye_safety.sce   -   PRD HW-2
//  IEC 60825-1 Ed.3 (2014) Class 1 analysis for the 905 nm emitter.
//
//  RUN SECOND (after scan_coverage.sce conceptually, but it is
//  independently runnable). This script CAPS the peak optical power that
//  every other script is allowed to assume, so it is the real starting
//  point of the design.
//
//  IMPORTANT HONESTY NOTE, repeat it in the report and to judges:
//  this is a DESIGN-STAGE calculation, not a certification. Formal
//  Class 1 classification requires measurement in an accredited lab
//  under the standard's measurement conditions. What we demonstrate is
//  that the design closes against the published limits with margin.
// =====================================================================
exec("params.sce", -1);
ensure_dirs();

function s = string_pf(r)
    if r <= 1.0 then s = "PASS"; else s = "FAIL"; end
endfunction

mprintf("\n===== EYE SAFETY (HW-2) - IEC 60825-1 Ed.3 Class 1 =====\n\n");

// ---------------------------------------------------------------------
//  QUOTED LIMIT  (authoritative - from the standard, not from us)
//    Class 1 AEL, 700-1050 nm, single pulse, 1 ns <= t < 18 us:
//        AEL_single = 7e-4 * C4 * C6 * t^0.75      [J]
//    C4 = 10^(0.002*(lambda_nm - 700))      wavelength correction
//    C6 = 1 for a small (point) apparent source
//    Repetitive pulses, requirement 3 of 4.3 f):
//        AEL_train = C5 * AEL_single,  C5 = N^-0.25, floored at 0.4
//        N = number of pulses a fixed eye receives within T2 = 10 s
//    Measurement condition 3: 7 mm aperture stop at 100 mm from source.
// ---------------------------------------------------------------------
LAMBDA_NM   = LAMBDA * 1e9;
C4          = 10^(0.002*(LAMBDA_NM - 700));   // QUOTED formula
C6          = 1.0;                            // small source
T2          = 10.0;                           // [s] time base
APERTURE_ST = 7.0e-3;                         // [m] condition 3 stop
DIST_ST     = 0.100;                          // [m] condition 3 distance

AEL_single = 7e-4 * C4 * C6 * PULSE_FWHM^0.75;   // [J]

mprintf("QUOTED LIMIT\n");
mprintf("  wavelength                      %.0f nm\n", LAMBDA_NM);
mprintf("  C4 = 10^(0.002*(lam-700))       %.4f\n", C4);
mprintf("  C6 (small source)               %.1f\n", C6);
mprintf("  pulse duration t                %.1f ns\n", PULSE_FWHM*1e9);
mprintf("  AEL_single = 7e-4*C4*C6*t^0.75  %.4f nJ\n\n", AEL_single*1e9);

// ---------------------------------------------------------------------
//  DESIGN PARAMETERS (ours) and DERIVED exposure
// ---------------------------------------------------------------------
// How many pulses can a stationary eye actually receive? The beam is
// SCANNED. A fixed eye sits in one beam direction, so it is hit only
// N_ACC times per frame, not PRF times per second. This is the single
// most important line in the whole calculation.
n_dir      = ceil((FOV_AZ_DEG*%pi/180)/ANG_PITCH) ..
             * ceil((FOV_EL_DEG*%pi/180)/ANG_PITCH);
frame_rate = PRF / (n_dir * N_ACC);
N_pulses   = N_ACC * frame_rate * T2;
C5         = max(N_pulses^(-0.25), 0.4);
AEL_train  = C5 * AEL_single;

mprintf("DESIGN PARAMETERS\n");
mprintf("  peak optical power              %.3f W\n", P_PEAK);
mprintf("  pulse energy  E = P*t           %.3f nJ\n", E_PULSE*1e9);
mprintf("  PRF                             %.1f kHz\n", PRF/1e3);
mprintf("  beam directions per frame       %.0f\n", n_dir);
mprintf("  frame rate                      %.2f Hz\n", frame_rate);
mprintf("  exit aperture D_TX              %.1f mm\n", D_TX*1e3);
mprintf("  divergence                      %.1f mrad\n\n", DIV_TX*1e3);

mprintf("DERIVED\n");
mprintf("  pulses a fixed eye sees in %.0fs  %.0f\n", T2, N_pulses);
mprintf("  C5 = max(N^-0.25, 0.4)          %.4f\n", C5);
mprintf("  AEL per pulse (Rule 3)          %.4f nJ\n", AEL_train*1e9);

// Fraction of the beam that enters the 7 mm measurement stop at 100 mm.
// Uniform (top-hat) beam assumption, which is CONSERVATIVE for a real
// Gaussian-ish diode only if the stop is not centred on the hot spot;
// state this limitation in the report.
d_beam_100 = D_TX + DIV_TX*DIST_ST;
frac_stop  = min((APERTURE_ST/d_beam_100)^2, 1.0);
E_access   = E_PULSE * frac_stop;

mprintf("  beam diameter at %.0f mm         %.2f mm\n", DIST_ST*1e3, d_beam_100*1e3);
mprintf("  fraction into the 7 mm stop     %.5f\n", frac_stop);
mprintf("  accessible energy per pulse     %.4f nJ\n\n", E_access*1e9);

// ---------------------------------------------------------------------
//  THE THREE REQUIREMENTS OF 4.3 f)
// ---------------------------------------------------------------------
r1 = E_access / AEL_single;                      // single pulse
r3 = E_access / AEL_train;                       // pulse train, Rule 3
// Rule 2, average power through the stop over T2, against the CW AEL.
// CW Class 1 AEL for 700-1050 nm, t > 10 s:  3.9e-3 * C4 * C7  [W]
AEL_cw   = 3.9e-3 * C4 * 1.0;
P_access = E_access * N_pulses / T2;
r2 = P_access / AEL_cw;

mprintf("THE THREE REQUIREMENTS\n");
mprintf("  Rule 1 single pulse   %.4f nJ / %.4f nJ = %.3f  %s\n", ..
        E_access*1e9, AEL_single*1e9, r1, string_pf(r1));
mprintf("  Rule 2 average power  %.4f uW / %.4f mW = %.6f  %s\n", ..
        P_access*1e6, AEL_cw*1e3, r2, string_pf(r2));
mprintf("  Rule 3 pulse train    %.4f nJ / %.4f nJ = %.3f  %s\n", ..
        E_access*1e9, AEL_train*1e9, r3, string_pf(r3));

worst = max([r1 r2 r3]);
mprintf("\n  WORST CASE RATIO      %.3f\n", worst);
if worst <= 1.0 then
    mprintf("  CONCLUSION: design is Class 1 with %.1f%% margin.\n", (1-worst)*100);
else
    mprintf("  CONCLUSION: design FAILS Class 1 by %.1fx. Redesign below.\n", worst);
end

// ---------------------------------------------------------------------
//  DESIGN SPACE: what peak power is allowed, against exit aperture
//  This is the figure that shows WHY D_TX = 50 mm was chosen.
// ---------------------------------------------------------------------
D_sweep = linspace(0.005, 0.080, 300);
P_allow = zeros(1, length(D_sweep));
for i = 1:length(D_sweep)
    db = D_sweep(i) + DIV_TX*DIST_ST;
    fr = min((APERTURE_ST/db)^2, 1.0);
    P_allow(i) = AEL_train / fr / PULSE_FWHM;
end

// A naive 75 W emitter, for contrast in the report
P_NAIVE = 75.0;
db_n = 0.010 + DIV_TX*DIST_ST;
fr_n = min((APERTURE_ST/db_n)^2, 1.0);
ratio_naive = (P_NAIVE*PULSE_FWHM*fr_n) / AEL_train;
mprintf("\nCONTRAST (for the report):\n");
mprintf("  a textbook 75 W emitter behind a 10 mm aperture would be\n");
mprintf("  %.0fx over the Class 1 limit. Eye safety, not the link budget,\n", ratio_naive);
mprintf("  is what sizes this emitter.\n");

scf(1); clf();
plot(D_sweep*1e3, P_allow, "b-");
plot([D_TX*1e3 D_TX*1e3], [0 max(P_allow)], "k:");
plot(D_TX*1e3, P_PEAK, "ro");
legend(["Class 1 peak power ceiling"; "chosen exit aperture"], 2);
xtitle("Class 1 peak-power ceiling vs exit aperture (905 nm, 5 ns, scanned)", ..
       "exit aperture diameter [mm]", "allowed peak optical power [W]");
xgrid();
try
    xs2png(1, "../figures/fig_eye_safety.png");
    xs2svg(1, "../figures/svg/fig_eye_safety.svg");
catch
    mprintf("  (PNG export skipped)\n");
end

L = ["quantity,value,unit,provenance";
     msprintf("C4,%.4f,-,quoted IEC 60825-1", C4);
     msprintf("AEL_single,%.6e,J,quoted formula", AEL_single);
     msprintf("N_pulses_T2,%.0f,-,derived", N_pulses);
     msprintf("C5,%.4f,-,quoted rule", C5);
     msprintf("AEL_train,%.6e,J,derived", AEL_train);
     msprintf("E_pulse,%.6e,J,design", E_PULSE);
     msprintf("frac_stop,%.6f,-,derived", frac_stop);
     msprintf("E_accessible,%.6e,J,derived", E_access);
     msprintf("rule1_ratio,%.4f,-,derived", r1);
     msprintf("rule2_ratio,%.6f,-,derived", r2);
     msprintf("rule3_ratio,%.4f,-,derived", r3);
     msprintf("worst_ratio,%.4f,-,derived", worst)];
mputl(L, "../results/eye_safety.csv");
mprintf("\nSaved ../results/eye_safety.csv and ../figures/fig_eye_safety.png\n\n");
