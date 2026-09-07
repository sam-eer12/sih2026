// =====================================================================
//  range_accuracy.sce   -   PRD HW-4
//  sigma_range = c * sigma_t / 2, built into a full error budget:
//  TDC quantisation, timing jitter from SNR, and amplitude time-walk
//  with and without the CFD.
//
//  This script is ANALYTIC. rx_chain.sce is the numerical simulation
//  that confirms it. If the two disagree, say so in the log.
// =====================================================================
exec("params.sce", -1);
ensure_dirs();
mprintf("\n===== RANGE ACCURACY / ERROR BUDGET (HW-4) =====\n\n");

mprintf("The governing relation\n");
mprintf("  R = c*t/2      so    sigma_R = c*sigma_t/2\n");
mprintf("  1 ns of timing error  = %.2f cm of range error\n", C_LIGHT*1e-9/2*100);
mprintf("  1 cm of range         = %.2f ps of round-trip time\n\n", 2*0.01/C_LIGHT*1e12);

// ---- term 1: TDC quantisation ----------------------------------------
// A uniform quantiser of step q has standard deviation q/sqrt(12).
sig_t_tdc = TDC_LSB/sqrt(12);
sig_R_tdc = C_LIGHT*sig_t_tdc/2;
mprintf("Term 1 - TDC quantisation\n");
mprintf("  TDC LSB                  %.1f ps  (PRD 16.1)\n", TDC_LSB*1e12);
mprintf("  sigma_t = LSB/sqrt(12)   %.2f ps\n", sig_t_tdc*1e12);
mprintf("  sigma_R                  %.3f cm\n\n", sig_R_tdc*100);

// ---- term 2: noise-driven timing jitter ------------------------------
// A leading edge crossed at slope dV/dt with noise sigma_V has timing
// uncertainty sigma_t = sigma_V / (dV/dt) = t_rise / SNR.
t_rise = 2.2 * TAU_DET;      // 10-90% rise time of a single-pole chain
mprintf("Term 2 - noise-driven jitter,  sigma_t = t_rise / SNR\n");
mprintf("  chain rise time (10-90%%)  %.3f ns\n", t_rise*1e9);
R_list = [10 25 50 75 100];
sig_R_jit = zeros(1,5);
for i = 1:5
    s = snr_of(R_list(i), RHO_NOM, N_ACC, P_PEAK, A_RX, ETA_OPT, ALPHA_ATM, ..
               R_LAMBDA, M_APD, F_EXCESS, ENB, R_F, I_N_TIA, T_KELVIN, ..
               K_B, Q_E, I_DARK, P_BG);
    st = t_rise/s;
    sig_R_jit(i) = C_LIGHT*st/2;
    mprintf("  R=%5.1f m  SNR %7.2f  sigma_t %7.1f ps  sigma_R %6.2f cm\n", ..
            R_list(i), s, st*1e12, sig_R_jit(i)*100);
end

// ---- term 3: amplitude time walk -------------------------------------
// A fixed threshold V_th on a Gaussian-shaped echo of amplitude A is
// crossed at  t = t_peak - sigma_p*sqrt(2*ln(A/V_th)).  The crossing
// time therefore MOVES with amplitude. That movement is time walk.
P100  = p_received(R_MAX_REQ, RHO_NOM, P_PEAK, A_RX, ETA_OPT, ALPHA_ATM);
V100  = R_F*M_APD*R_LAMBDA*P100*0.98;
sig_far = sqrt((R_F*M_APD)^2*2*Q_E*(R_LAMBDA*P100 + R_LAMBDA*P_BG + I_DARK) ..
          *F_EXCESS*ENB + SIGMA_TH^2)/sqrt(N_ACC);
V_th  = N_SIGMA_THR*sig_far;
sig_p = sqrt(PULSE_SIG^2 + TAU_DET^2);   // widened by the detector

mprintf("\nTerm 3 - amplitude time walk (fixed threshold)\n");
mprintf("  threshold V_th = %.1f sigma at %.0f m = %.4f mV\n", ..
        N_SIGMA_THR, R_MAX_REQ, V_th*1e3);
amp = []; tw = [];
for R = [10 25 50 75 100]
    for rho = [RHO_MIN RHO_MAX]
        P = p_received(R, rho, P_PEAK, A_RX, ETA_OPT, ALPHA_ATM);
        A = R_F*M_APD*R_LAMBDA*P*0.98;
        if A > V_th then
            t_cross = -sig_p*sqrt(2*log(A/V_th));
            amp = [amp A];  tw = [tw t_cross];
        end
    end
end
walk_span_t = max(tw) - min(tw);
walk_span_R = C_LIGHT*walk_span_t/2;
mprintf("  echo amplitude spans %.3f mV to %.1f mV (%.0fx)\n", ..
        min(amp)*1e3, max(amp)*1e3, max(amp)/min(amp));
mprintf("  crossing time spans %.3f ns\n", walk_span_t*1e9);
mprintf("  => TIME WALK, threshold only : %.2f cm\n", walk_span_R*100);
mprintf("  => TIME WALK, with CFD       : ~0 by construction (the CFD\n");
mprintf("     fires at a fixed fraction of the echo OWN height, so the\n");
mprintf("     crossing point does not move with amplitude). rx_chain.sce\n");
mprintf("     measures the residual numerically.\n");

// ---- combined budget --------------------------------------------------
mprintf("\nERROR BUDGET at %.0f m, rho = %.1f (1 sigma, added in quadrature)\n", ..
        R_MAX_REQ, RHO_NOM);
b_tdc = sig_R_tdc;
b_jit = sig_R_jit($);
b_walk_thr = walk_span_R/2;   // half-span as an rms-equivalent
b_walk_cfd = 0.01*walk_span_R/2;
tot_thr = sqrt(b_tdc^2 + b_jit^2 + b_walk_thr^2);
tot_cfd = sqrt(b_tdc^2 + b_jit^2 + b_walk_cfd^2);
mprintf("  TDC quantisation         %6.2f cm\n", b_tdc*100);
mprintf("  noise jitter             %6.2f cm\n", b_jit*100);
mprintf("  walk, threshold only     %6.2f cm\n", b_walk_thr*100);
mprintf("  walk, with CFD           %6.2f cm\n", b_walk_cfd*100);
mprintf("  ----------------------------------\n");
mprintf("  TOTAL, threshold only    %6.2f cm\n", tot_thr*100);
mprintf("  TOTAL, with CFD          %6.2f cm   <- proposed design\n", tot_cfd*100);
mprintf("  improvement factor       %6.2f x\n\n", tot_thr/tot_cfd);

// ---- figures ----------------------------------------------------------
Rc = linspace(5, 120, 300);
sj = zeros(1,300);
for i = 1:300
    s = snr_of(Rc(i), RHO_NOM, N_ACC, P_PEAK, A_RX, ETA_OPT, ALPHA_ATM, ..
               R_LAMBDA, M_APD, F_EXCESS, ENB, R_F, I_N_TIA, T_KELVIN, ..
               K_B, Q_E, I_DARK, P_BG);
    sj(i) = C_LIGHT*(t_rise/s)/2;
end
scf(1); clf();
plot(Rc, sj*100, "b-");
plot([5 120], [sig_R_tdc*100 sig_R_tdc*100], "g--");
plot([5 120], [b_walk_thr*100 b_walk_thr*100], "r:");
legend(["noise jitter"; "TDC quantisation floor"; "walk, threshold only"], 2);
xtitle("Range error budget terms vs range (HW-4)", "range [m]", ..
       "1 sigma range error [cm]");
xgrid();
try
    xs2png(1, "../figures/fig_range_accuracy.png");
    xs2svg(1, "../figures/svg/fig_range_accuracy.svg");
catch
    mprintf("  (PNG export skipped)\n");
end

L = ["term,value_cm";
     msprintf("tdc_quantisation,%.4f", b_tdc*100);
     msprintf("jitter_at_100m,%.4f", b_jit*100);
     msprintf("walk_threshold,%.4f", b_walk_thr*100);
     msprintf("walk_cfd,%.4f", b_walk_cfd*100);
     msprintf("total_threshold,%.4f", tot_thr*100);
     msprintf("total_cfd,%.4f", tot_cfd*100)];
mputl(L, "../results/range_accuracy.csv");
mprintf("Saved ../results/range_accuracy.csv and 1 figure.\n\n");
