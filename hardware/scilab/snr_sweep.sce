// =====================================================================
//  snr_sweep.sce   -   PRD HW-1 (parameter sweeps)
//  Sweeps reflectivity, receiver aperture and sunlight background to
//  show where the design margin lives and what breaks it first.
// =====================================================================
exec("params.sce", -1);
ensure_dirs();
mprintf("\n===== SNR / DESIGN MARGIN SWEEPS (HW-1) =====\n\n");

function s = snr_cfg(R, rho, D_rx, e_sun, n_acc)
    A  = %pi*D_rx^2/4;
    Pb = rho * e_sun * FILTER_BW * THETA_RX^2 * A * ETA_OPT / 4;
    s  = snr_of(R, rho, n_acc, P_PEAK, A, ETA_OPT, ALPHA_ATM, R_LAMBDA, ..
                M_APD, F_EXCESS, ENB, R_F, I_N_TIA, T_KELVIN, K_B, Q_E, ..
                I_DARK, Pb);
endfunction

// ---- sweep 1: reflectivity -------------------------------------------
rho_s = linspace(0.1, 0.9, 60);
s1 = zeros(1,60);
for i = 1:60, s1(i) = snr_cfg(R_MAX_REQ, rho_s(i), D_RX, E_SUN, N_ACC); end
scf(1); clf();
plot(rho_s, s1, "b-");
plot([0.1 0.9], [SNR_THRESH SNR_THRESH], "r--");
legend(["SNR at 100 m"; "detection threshold"], 1);
xtitle("SNR vs target reflectivity at 100 m", "reflectivity [-]", "SNR [-]");
xgrid();
try
    xs2png(1, "../figures/fig_sweep_reflectivity.png");
catch
    mprintf("  (PNG export skipped)\n");
end
mprintf("Reflectivity sweep at %.0f m: SNR %.2f (rho=0.1) to %.2f (rho=0.9)\n", ..
        R_MAX_REQ, s1(1), s1($));

// ---- sweep 2: receiver aperture --------------------------------------
D_s = linspace(0.015, 0.080, 60);
s2 = zeros(1,60);
for i = 1:60, s2(i) = snr_cfg(R_MAX_REQ, RHO_NOM, D_s(i), E_SUN, N_ACC); end
k = find(s2 >= SNR_THRESH);
if isempty(k) then D_need = %nan; else D_need = D_s(k(1)); end
scf(2); clf();
plot(D_s*1e3, s2, "b-");
plot([15 80], [SNR_THRESH SNR_THRESH], "r--");
plot([D_RX*1e3 D_RX*1e3], [0 max(s2)], "k:");
legend(["SNR at 100 m, rho=0.1"; "detection threshold"; "chosen aperture"], 2);
xtitle("SNR vs receiver aperture", "receiver aperture [mm]", "SNR [-]");
xgrid();
try
    xs2png(2, "../figures/fig_sweep_aperture.png");
catch
    mprintf("  (PNG export skipped)\n");
end
mprintf("Aperture sweep: minimum aperture for SNR>=%.0f at 100 m rho=0.1 is %.1f mm\n", ..
        SNR_THRESH, D_need*1e3);
mprintf("  chosen %.0f mm -> aperture margin %.1f mm\n", D_RX*1e3, (D_RX-D_need)*1e3);

// ---- sweep 3: sunlight background ------------------------------------
E_s = linspace(0, 1.5, 60);
s3 = zeros(1,60);
for i = 1:60, s3(i) = snr_cfg(R_MAX_REQ, RHO_NOM, D_RX, E_s(i), N_ACC); end
scf(3); clf();
plot(E_s, s3, "b-");
plot([0 1.5], [SNR_THRESH SNR_THRESH], "r--");
plot([E_SUN E_SUN], [0 max(s3)], "k:");
legend(["SNR at 100 m, rho=0.1"; "detection threshold"; "assumed daylight"], 3);
xtitle("SNR vs solar background", ..
       "solar spectral irradiance at 905 nm [W/(m^2 nm)]", "SNR [-]");
xgrid();
try
    xs2png(3, "../figures/fig_sweep_sunlight.png");
catch
    mprintf("  (PNG export skipped)\n");
end
mprintf("Sunlight sweep: SNR %.2f in darkness -> %.2f at %.1f W/(m^2 nm)\n", ..
        s3(1), snr_cfg(R_MAX_REQ,RHO_NOM,D_RX,E_SUN,N_ACC), E_SUN);
mprintf("  background costs %.1f%% of SNR at the design point.\n", ..
        (1 - snr_cfg(R_MAX_REQ,RHO_NOM,D_RX,E_SUN,N_ACC)/s3(1))*100);

// ---- sweep 4: accumulation -------------------------------------------
n_s = 1:16;
s4 = zeros(1,16);
for i = 1:16, s4(i) = snr_cfg(R_MAX_REQ, RHO_NOM, D_RX, E_SUN, n_s(i)); end
scf(4); clf();
plot(n_s, s4, "b-o");
plot([1 16], [SNR_THRESH SNR_THRESH], "r--");
plot([N_ACC N_ACC], [0 max(s4)], "k:");
legend(["SNR at 100 m, rho=0.1"; "detection threshold"; "chosen N_ACC"], 2);
xtitle("SNR vs pulses accumulated per direction", ..
       "pulses accumulated [-]", "SNR [-]");
xgrid();
try
    xs2png(4, "../figures/fig_sweep_accumulation.png");
catch
    mprintf("  (PNG export skipped)\n");
end
mprintf("Accumulation sweep: N=1 gives SNR %.2f, N=%d gives %.2f (sqrt(N) law)\n", ..
        s4(1), N_ACC, s4(N_ACC));

L = ["sweep,x,snr"];
for i=1:60, L=[L; msprintf("reflectivity,%.4f,%.4f", rho_s(i), s1(i))]; end
for i=1:60, L=[L; msprintf("aperture_m,%.4f,%.4f", D_s(i), s2(i))]; end
for i=1:60, L=[L; msprintf("sunlight,%.4f,%.4f", E_s(i), s3(i))]; end
for i=1:16, L=[L; msprintf("accumulation,%d,%.4f", n_s(i), s4(i))]; end
mputl(L, "../results/snr_sweep.csv");
mprintf("\nSaved ../results/snr_sweep.csv and 4 figures.\n\n");
