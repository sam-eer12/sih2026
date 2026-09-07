// =====================================================================
//  link_budget.sce   -   PRD HW-1
//  Received optical power and SNR against range, reflectivity 0.1-0.9,
//  with atmospheric transmission and receiver aperture, and the derived
//  maximum range at a stated SNR threshold.
// =====================================================================
exec("params.sce", -1);
ensure_dirs();
mprintf("\n===== LINK BUDGET (HW-1) =====\n\n");

R = linspace(1, 250, 2000);
rho_list = [0.1 0.3 0.5 0.7 0.9];

mprintf("Configuration\n");
mprintf("  peak optical power    %.2f W   (capped by eye_safety.sce)\n", P_PEAK);
mprintf("  receiver aperture     %.1f mm\n", D_RX*1e3);
mprintf("  optical efficiency    %.2f\n", ETA_OPT);
mprintf("  atmospheric alpha     %.1f /km\n", ALPHA_ATM*1e3);
mprintf("  accumulation          %d pulses\n", N_ACC);
mprintf("  background power      %.3f nW (range independent)\n\n", P_BG*1e9);

// ---- term-by-term budget at the design range, for the report table ---
Rd = R_MAX_REQ;
geo = A_RX/(%pi*Rd^2);
atm = exp(-2*ALPHA_ATM*Rd);
mprintf("Term-by-term budget at %.0f m, rho = %.1f\n", Rd, RHO_NOM);
mprintf("  transmitted peak power        %10.3e W\n", P_PEAK);
mprintf("  x target reflectivity  %.2f     %10.3e W\n", RHO_NOM, P_PEAK*RHO_NOM);
mprintf("  x geometric A/(pi R^2) %.3e  %10.3e W\n", geo, P_PEAK*RHO_NOM*geo);
mprintf("  x optical efficiency   %.2f     %10.3e W\n", ETA_OPT, P_PEAK*RHO_NOM*geo*ETA_OPT);
mprintf("  x atmosphere (2-way)   %.4f   %10.3e W  <- received\n\n", atm, ..
        P_PEAK*RHO_NOM*geo*ETA_OPT*atm);

// ---- curves ----------------------------------------------------------
scf(1); clf();
cols = ["r-","m-","g-","c-","b-"];
for i = 1:5
    P = p_received(R, rho_list(i), P_PEAK, A_RX, ETA_OPT, ALPHA_ATM);
    plot(R, P*1e9, cols(i));
end
legend(["rho=0.1";"rho=0.3";"rho=0.5";"rho=0.7";"rho=0.9"], 1);
xtitle("Received optical power vs range (HW-1)", "range [m]", ..
       "received peak optical power [nW]");
xgrid();
try
    xs2png(1, "../figures/fig_link_power.png");
catch
    mprintf("  (PNG export skipped)\n");
end

scf(2); clf();
R_max_list = zeros(1,5);
for i = 1:5
    s = snr_of(R, rho_list(i), N_ACC, P_PEAK, A_RX, ETA_OPT, ALPHA_ATM, ..
               R_LAMBDA, M_APD, F_EXCESS, ENB, R_F, I_N_TIA, T_KELVIN, ..
               K_B, Q_E, I_DARK, P_BG);
    plot(R, s, cols(i));
    k = find(s >= SNR_THRESH);
    if isempty(k) then R_max_list(i) = 0; else R_max_list(i) = R(k($)); end
end
plot([1 250], [SNR_THRESH SNR_THRESH], "k--");
plot([R_MAX_REQ R_MAX_REQ], [1 1000], "k:");
legend(["rho=0.1";"rho=0.3";"rho=0.5";"rho=0.7";"rho=0.9"; ..
        msprintf("SNR threshold = %.0f", SNR_THRESH)], 1);
xtitle("SNR vs range (HW-1)", "range [m]", "amplitude SNR [-]");
xgrid();
try
    xs2png(2, "../figures/fig_link_snr.png");
catch
    mprintf("  (PNG export skipped)\n");
end

mprintf("Maximum range at SNR >= %.0f\n", SNR_THRESH);
for i = 1:5
    mprintf("  rho = %.1f  ->  R_max = %6.1f m   (SNR at %.0f m = %6.2f)\n", ..
        rho_list(i), R_max_list(i), R_MAX_REQ, ..
        snr_of(R_MAX_REQ, rho_list(i), N_ACC, P_PEAK, A_RX, ETA_OPT, ..
               ALPHA_ATM, R_LAMBDA, M_APD, F_EXCESS, ENB, R_F, I_N_TIA, ..
               T_KELVIN, K_B, Q_E, I_DARK, P_BG));
end
mprintf("\n  PRD requirement is %.0f m (config.yaml grid.r_max, PS-6).\n", R_MAX_REQ);
if R_max_list(1) >= R_MAX_REQ then
    mprintf("  MET at the worst-case reflectivity 0.1, margin %.1f m.\n\n", ..
            R_max_list(1) - R_MAX_REQ);
else
    mprintf("  NOT met at rho=0.1. Worst-case range is %.1f m.\n\n", R_max_list(1));
end

L = ["rho,R_max_m,SNR_at_100m"];
for i = 1:5
    L = [L; msprintf("%.1f,%.2f,%.3f", rho_list(i), R_max_list(i), ..
         snr_of(R_MAX_REQ, rho_list(i), N_ACC, P_PEAK, A_RX, ETA_OPT, ..
                ALPHA_ATM, R_LAMBDA, M_APD, F_EXCESS, ENB, R_F, I_N_TIA, ..
                T_KELVIN, K_B, Q_E, I_DARK, P_BG))];
end
mputl(L, "../results/link_budget.csv");
mprintf("Saved ../results/link_budget.csv and 2 figures.\n\n");
