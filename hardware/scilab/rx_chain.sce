// =====================================================================
//  rx_chain.sce   -   PRD HW-3
//  Receiver-chain simulation: pulse -> APD -> TIA -> CFD -> TDC with
//  noise, showing measured range against true range.
//
//  This is the documented PURE-CODE EQUIVALENT of the Simulink model in
//  PRD 16.3 / 16.4: discrete-time convolution of the laser pulse with
//  the detector impulse response, plus shot and thermal noise, with the
//  CFD and TDC applied numerically. Same waveforms, same range-error
//  figures, no Simulink. PRD 16.4 explicitly authorises this path.
//
//  SIMULATION ONLY. No hardware was built or measured.
//  Runtime roughly 30-90 s.
// =====================================================================
exec("params.sce", -1);
ensure_dirs();
mprintf("\n===== RECEIVER CHAIN (HW-3) - SIMULATION =====\n\n");

N_TRIALS = 100;                 // noisy shots per range
R_CAL    = 50.0;                // calibration range [m]
R_LIST   = 10:5:100;            // ranges to sweep [m]

// ---- validity checks --------------------------------------------------
T_REC = (N_SAMP-1)*DT_SIM;
R_REC = C_LIGHT*T_REC/2;
if DT_SIM >= PULSE_FWHM/10 then
    error("DT_SIM must be <= 1/10 of PULSE_FWHM.");
end
if R_REC <= max(R_LIST)*1.05 then
    error(msprintf("record covers %.1f m, need > %.1f m; raise N_SAMP.", ..
          R_REC, max(R_LIST)));
end
if CFD_DELAY <= DT_SIM then
    error("CFD_DELAY must span several time steps.");
end
mprintf("Checks passed. Record %.1f ns covers %.1f m.\n\n", T_REC*1e9, R_REC);

// ---- detector impulse response (single pole, unit area) ---------------
N_H  = 400;
t_h  = (0:N_H-1)*DT_SIM;
h    = exp(-t_h/TAU_DET)/TAU_DET;
h    = h/(sum(h)*DT_SIM);
Hd   = fft([h*DT_SIM, zeros(1, 2*N_SAMP - N_H)], -1);
t_ax = (0:N_SAMP-1)*DT_SIM;
N_CFD = round(CFD_DELAY/DT_SIM);

grand("setgen", "mt");
grand("setsd", RNG_SEED);

// ---- threshold level, referred to the noise at the design range -------
P_far = p_received(R_MAX_REQ, RHO_NOM, P_PEAK, A_RX, ETA_OPT, ALPHA_ATM);
I_far = R_LAMBDA*P_far;
SIG_1 = sqrt((R_F*M_APD)^2*2*Q_E*(I_far + R_LAMBDA*P_BG + I_DARK) ..
        *F_EXCESS*ENB + SIGMA_TH^2);
// The payload accumulates N_ACC pulses per beam direction (params.sce).
// Averaging N shots divides the noise by sqrt(N), so the threshold must
// be referred to the ACCUMULATED noise, not the single-shot noise.
SIG_FAR = SIG_1/sqrt(N_ACC);
V_TH    = N_SIGMA_THR*SIG_FAR;
V_PK    = R_F*M_APD*I_far*0.98;
mprintf("Single-shot noise at %.0f m   %.5f mV rms\n", R_MAX_REQ, SIG_1*1e3);
mprintf("After %d-pulse accumulation   %.5f mV rms\n", N_ACC, SIG_FAR*1e3);
mprintf("Threshold (%.0f sigma)          %.5f mV\n", N_SIGMA_THR, V_TH*1e3);
mprintf("Peak echo at %.0f m           %.5f mV  (%.0f%% of peak)\n", ..
        R_MAX_REQ, V_PK*1e3, V_TH/V_PK*100);
if V_TH >= V_PK then
    mprintf("\n  *** WARNING: the threshold is ABOVE the echo peak at %.0f m.\n", R_MAX_REQ);
    mprintf("  *** Nothing beyond that range can be detected, and any\n");
    mprintf("  *** apparent detection is a noise spike. Raise N_ACC, raise\n");
    mprintf("  *** D_RX, or lower N_SIGMA_THR in params.sce.\n\n");
end
mprintf("\n");

// ---- calibration: remove each method's fixed electrical offset --------
t0c  = 2*R_CAL/C_LIGHT;
Pc   = p_received(R_CAL, RHO_NOM, P_PEAK, A_RX, ETA_OPT, ALPHA_ATM);
vc   = R_F*M_APD*R_LAMBDA*conv_h(Pc*exp(-0.5*((t_ax-t0c)/PULSE_SIG).^2), Hd, N_SAMP);
t_a  = xing_up(vc, V_TH, 1, DT_SIM);
if isnan(t_a) then error("Calibration echo never reaches the threshold."); end
t_b  = xing_dn(cfd_signal(vc, CFD_FRACTION, N_CFD), round(t_a/DT_SIM), DT_SIM);
if isnan(t_b) then error("No CFD zero crossing at the calibration range."); end
OFF_THR = t_a - t0c;
OFF_CFD = t_b - t0c;
mprintf("Calibration at %.0f m: threshold fires %.3f ns and CFD %.3f ns\n", ..
        R_CAL, -OFF_THR*1e9, -OFF_CFD*1e9);
mprintf("before the echo peak. Both offsets are constant and removed.\n\n");

// ---- main sweep -------------------------------------------------------
nR = length(R_LIST);
bias_thr = zeros(1,nR); jit_thr = zeros(1,nR);
bias_cfd = zeros(1,nR); jit_cfd = zeros(1,nR);
det_thr  = zeros(1,nR); det_cfd = zeros(1,nR); snr_l = zeros(1,nR);

mprintf("Sweeping %d ranges x %d shots.\n", nR, N_TRIALS);
for kR = 1:nR
    R  = R_LIST(kR);
    t0 = 2*R/C_LIGHT;
    Pp = p_received(R, RHO_NOM, P_PEAK, A_RX, ETA_OPT, ALPHA_ATM);
    ifl = max(R_LAMBDA*conv_h(Pp*exp(-0.5*((t_ax-t0)/PULSE_SIG).^2), Hd, N_SAMP), 0);
    v_cl = R_F*M_APD*ifl;
    sg = sqrt((R_F*M_APD*sqrt(2*Q_E*(ifl + R_LAMBDA*P_BG + I_DARK)*F_EXCESS*ENB)).^2 ..
              + SIGMA_TH^2);
    snr_l(kR) = max(v_cl)/max(sg)*sqrt(N_ACC);

    et = []; ec = [];
    for kT = 1:N_TRIALS
        // Accumulate N_ACC independent shots, exactly as the hardware
        // does, then time the averaged waveform.
        v = zeros(1, N_SAMP);
        for kA = 1:N_ACC
            w  = grand(1, N_SAMP, "nor", 0, 1);
            nb = conv_h(w, Hd, N_SAMP);
            sd = stdev(nb);  if sd > 0 then nb = nb/sd; end
            v  = v + min(max(v_cl + nb .* sg, -V_SAT), V_SAT);
        end
        v = v / N_ACC;

        ta = xing_up(v, V_TH, 1, DT_SIM);
        tb = %nan;
        if ~isnan(ta) then
            // A real CFD needs an ARMING comparator, otherwise its zero
            // crossing detector triggers on noise before the echo. The
            // threshold crossing is the arm.
            tb = xing_dn(cfd_signal(v, CFD_FRACTION, N_CFD), round(ta/DT_SIM), DT_SIM);
        end
        if ~isnan(ta) then
            et = [et, C_LIGHT*(round((ta-OFF_THR)/TDC_LSB)*TDC_LSB)/2 - R];
        end
        if ~isnan(tb) then
            ec = [ec, C_LIGHT*(round((tb-OFF_CFD)/TDC_LSB)*TDC_LSB)/2 - R];
        end
    end
    det_thr(kR) = length(et)/N_TRIALS;
    det_cfd(kR) = length(ec)/N_TRIALS;
    if length(et) > 1 then bias_thr(kR)=mean(et); jit_thr(kR)=stdev(et);
    else bias_thr(kR)=%nan; jit_thr(kR)=%nan; end
    if length(ec) > 1 then bias_cfd(kR)=mean(ec); jit_cfd(kR)=stdev(ec);
    else bias_cfd(kR)=%nan; jit_cfd(kR)=%nan; end
    mprintf("  R=%6.1f  SNR=%6.1f | THR bias %+7.3f jit %6.4f | CFD bias %+7.4f jit %6.4f\n", ..
            R, snr_l(kR), bias_thr(kR), jit_thr(kR), bias_cfd(kR), jit_cfd(kR));
end
rms_thr = sqrt(bias_thr.^2 + jit_thr.^2);
rms_cfd = sqrt(bias_cfd.^2 + jit_cfd.^2);

// ---- pure walk test: same range, different reflectivity, no noise -----
rho_s = [0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9];
we_t = zeros(1,9); we_c = zeros(1,9);
t0w = 2*R_CAL/C_LIGHT;
for k = 1:9
    Pp = p_received(R_CAL, rho_s(k), P_PEAK, A_RX, ETA_OPT, ALPHA_ATM);
    v  = min(R_F*M_APD*R_LAMBDA*conv_h(Pp*exp(-0.5*((t_ax-t0w)/PULSE_SIG).^2), ..
             Hd, N_SAMP), V_SAT);
    ta = xing_up(v, V_TH, 1, DT_SIM);
    if isnan(ta) then
        we_t(k)=%nan; we_c(k)=%nan;
    else
        we_t(k) = C_LIGHT*(ta-OFF_THR)/2 - R_CAL;
        tb = xing_dn(cfd_signal(v, CFD_FRACTION, N_CFD), round(ta/DT_SIM), DT_SIM);
        if isnan(tb) then we_c(k)=%nan; else we_c(k)=C_LIGHT*(tb-OFF_CFD)/2 - R_CAL; end
    end
end

// ---- sanity checks ----------------------------------------------------
mprintf("\n--- SANITY CHECKS (physics, not simulation output) ---\n");
for Rq = [10 50 100]
    mprintf("  R = %3d m -> t = %8.3f ns\n", Rq, 2*Rq/C_LIGHT*1e9);
end
mprintf("  1 cm  -> %6.2f ps        1 ns -> %6.3f m\n", 2*0.01/C_LIGHT*1e12, C_LIGHT*1e-9/2);
mprintf("  TDC LSB %.0f ps -> %5.2f mm    sim step %.0f ps -> %5.2f mm\n", ..
        TDC_LSB*1e12, C_LIGHT*TDC_LSB/2*1e3, DT_SIM*1e12, C_LIGHT*DT_SIM/2*1e3);

// ---- summary ----------------------------------------------------------
mprintf("\n--- RESULTS (simulated, %d shots/range) ---\n", N_TRIALS);
mprintf("  worst detection rate  THR %.0f%%  CFD %.0f%%", ..
        min(det_thr)*100, min(det_cfd)*100);
if min(det_thr) < 0.99 then
    mprintf("   <-- BELOW 100%%, see the threshold warning above\n");
else
    mprintf("   (100%% is what we want)\n");
end
mprintf("  time walk over %.0f-%.0f m   THR %.4f m   CFD %.4f m\n", ..
        min(R_LIST), max(R_LIST), max(bias_thr)-min(bias_thr), ..
        max(bias_cfd)-min(bias_cfd));
mprintf("  walk from rho 0.1->0.9      THR %.4f m   CFD %.6f m\n", ..
        max(we_t)-min(we_t), max(we_c)-min(we_c));
mprintf("  jitter at 100 m             THR %.4f m   CFD %.4f m\n", jit_thr($), jit_cfd($));
mprintf("  TOTAL rms at 100 m          THR %.4f m   CFD %.4f m\n", rms_thr($), rms_cfd($));
mprintf("  worst total over sweep      THR %.4f m   CFD %.4f m\n", ..
        max(rms_thr), max(rms_cfd));

// ---- figures ----------------------------------------------------------
scf(1); clf();
for k = 1:3
    R_DEMO = [10 50 100];
    Rd = R_DEMO(k);
    t0 = 2*Rd/C_LIGHT;
    Pp = p_received(Rd, RHO_NOM, P_PEAK, A_RX, ETA_OPT, ALPHA_ATM);
    ifl = max(R_LAMBDA*conv_h(Pp*exp(-0.5*((t_ax-t0)/PULSE_SIG).^2), Hd, N_SAMP), 0);
    vcl = R_F*M_APD*ifl;
    sg = sqrt((R_F*M_APD*sqrt(2*Q_E*(ifl+R_LAMBDA*P_BG+I_DARK)*F_EXCESS*ENB)).^2 + SIGMA_TH^2);
    v = zeros(1,N_SAMP);
    for kA = 1:N_ACC
        w = grand(1,N_SAMP,"nor",0,1); nb = conv_h(w,Hd,N_SAMP); nb = nb/stdev(nb);
        v = v + min(vcl + nb.*sg, V_SAT);
    end
    v = v/N_ACC;
    i1 = max(1, round((t0-20e-9)/DT_SIM)); i2 = min(N_SAMP, round((t0+20e-9)/DT_SIM));
    subplot(3,1,k);
    plot((t_ax(i1:i2)-t0)*1e9, v(i1:i2)*1e3, "b-");
    plot([-20 20], [V_TH V_TH]*1e3, "r--");
    xtitle(msprintf("Echo at R = %d m", Rd), "time from true echo peak [ns]", "TIA out [mV]");
    xgrid();
end
try
    xs2png(1, "../figures/fig_rx_waveforms.png");
catch
    mprintf("  (PNG export skipped)\n");
end

scf(2); clf();
plot(R_LIST, R_LIST, "k--");
plot(R_LIST, R_LIST+bias_thr, "r-o");
plot(R_LIST, R_LIST+bias_cfd, "b-s");
legend(["ideal"; "threshold"; "CFD"], 4);
xtitle("Measured vs true range (HW-3)", "true range [m]", "mean measured range [m]");
xgrid();
try
    xs2png(2, "../figures/fig_rx_measured_vs_true.png");
catch
    mprintf("  (PNG export skipped)\n");
end

scf(3); clf();
plot(R_LIST, bias_thr*100, "r-o");
plot(R_LIST, bias_cfd*100, "b-s");
plot([min(R_LIST) max(R_LIST)], [0 0], "k:");
legend(["threshold"; "CFD"], 4);
xtitle("Systematic range error (time walk)", "true range [m]", "mean error [cm]");
xgrid();
try
    xs2png(3, "../figures/fig_rx_walk.png");
catch
    mprintf("  (PNG export skipped)\n");
end

scf(4); clf();
plot(R_LIST, jit_thr*100, "r-o");
plot(R_LIST, jit_cfd*100, "b-s");
plot(R_LIST, rms_thr*100, "r--");
plot(R_LIST, rms_cfd*100, "b--");
legend(["THR jitter"; "CFD jitter"; "THR total rms"; "CFD total rms"], 2);
xtitle("Random and total range error", "true range [m]", "range error [cm]");
xgrid();
try
    xs2png(4, "../figures/fig_rx_jitter.png");
catch
    mprintf("  (PNG export skipped)\n");
end

scf(5); clf();
plot(rho_s, we_t*100, "r-o");
plot(rho_s, we_c*100, "b-s");
plot([0.1 0.9], [0 0], "k:");
legend(["threshold"; "CFD"], 1);
xtitle(msprintf("Pure time walk at %.0f m, no noise", R_CAL), ..
       "target reflectivity [-]", "range error [cm]");
xgrid();
try
    xs2png(5, "../figures/fig_rx_walk_vs_rho.png");
catch
    mprintf("  (PNG export skipped)\n");
end

L = ["true_range_m,snr,thr_bias_m,thr_jit_m,thr_rms_m,cfd_bias_m,cfd_jit_m,cfd_rms_m"];
for k = 1:nR
    L = [L; msprintf("%.2f,%.4f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f", R_LIST(k), ..
         snr_l(k), bias_thr(k), jit_thr(k), rms_thr(k), bias_cfd(k), ..
         jit_cfd(k), rms_cfd(k))];
end
mputl(L, "../results/rx_chain.csv");
L2 = ["reflectivity,thr_error_m,cfd_error_m"];
for k = 1:9
    L2 = [L2; msprintf("%.2f,%.6f,%.8f", rho_s(k), we_t(k), we_c(k))];
end
mputl(L2, "../results/rx_chain_walk.csv");
mprintf("\nSaved ../results/rx_chain.csv, rx_chain_walk.csv and 5 figures.\n");
mprintf("SIMULATED results from params.sce. Not measured hardware.\n\n");
