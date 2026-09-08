// =====================================================================
//  power_budget.sce   -   PRD HW-6
//  Per-component power and mass, totalled against a STATED drone
//  payload limit. PRD HW-6 does not give the limit; we state it in
//  params.sce (MASS_LIMIT_G, POWER_LIMIT_W) and defend it in the report.
//
//  EVERY per-component number below is a [CND] estimate for a component
//  CLASS, not a measured value and not a confirmed datasheet figure.
//  Day-9 task: replace each one with the number from the datasheet
//  named in ../docs/BOM.md and re-run. Nothing else changes.
// =====================================================================
exec("params.sce", -1);
ensure_dirs();
mprintf("\n===== POWER AND MASS BUDGET (HW-6) =====\n\n");

// name | electrical power W | mass g
names = ["905 nm laser diode + GaN driver";
         "TX collimating optics (50 mm)";
         "RX objective + 905 nm bandpass filter";
         "APD + HV bias supply";
         "TIA";
         "CFD comparator";
         "TDC";
         "MEMS mirror + driver ASIC";
         "MCU/FPGA aggregator + UDP PHY";
         "Power regulation losses";
         "PCB, connectors, wiring";
         "Enclosure, optical bench, mount"];

pw = [1.20; 0.00; 0.00; 0.35; 0.15; 0.25; 0.40; 1.50; 2.00; 1.00; 0.00; 0.00];
ms = [8.0;  45.0; 55.0; 6.0;  2.0;  2.0;  2.0;  12.0; 15.0; 25.0; 40.0; 120.0];

n = size(names, 1);
if (length(pw) <> n) | (length(ms) <> n) then
    error("power_budget.sce: names, power and mass lists differ in length.");
end

mprintf("%-40s %10s %10s\n", "component", "power [W]", "mass [g]");
mprintf("%s\n", "--------------------------------------------------------------");
for i = 1:n
    mprintf("%-40s %10.2f %10.1f\n", names(i), pw(i), ms(i));
end
mprintf("%s\n", "--------------------------------------------------------------");
P_tot = sum(pw);
M_tot = sum(ms);
mprintf("%-40s %10.2f %10.1f\n\n", "TOTAL", P_tot, M_tot);

P_marg = POWER_LIMIT_W - P_tot;
M_marg = MASS_LIMIT_G - M_tot;
mprintf("Against the stated payload limits\n");
mprintf("  power limit   %6.1f W   used %6.2f W   margin %6.2f W  (%5.1f %%)\n", ..
        POWER_LIMIT_W, P_tot, P_marg, P_marg/POWER_LIMIT_W*100);
mprintf("  mass limit    %6.1f g   used %6.1f g   margin %6.1f g  (%5.1f %%)\n", ..
        MASS_LIMIT_G, M_tot, M_marg, M_marg/MASS_LIMIT_G*100);
if (P_marg >= 0) & (M_marg >= 0) then
    mprintf("  RESULT: within both limits.\n\n");
else
    mprintf("  RESULT: OVER a limit. Reduce optics diameter or enclosure mass.\n\n");
end

mprintf("Optical power, for contrast with electrical power\n");
mprintf("  peak optical      %8.2f W   (%.1f ns, %.0f kHz)\n", P_PEAK, ..
        PULSE_FWHM*1e9, PRF/1e3);
mprintf("  average optical   %8.3f mW\n", P_AVG_OPT*1e3);
mprintf("  wall-plug electrical for the emitter is dominated by the driver\n");
mprintf("  and charging losses, not by the average optical power.\n\n");

// ---- figures ----------------------------------------------------------
scf(1); clf();
subplot(2,1,1);
bar(1:n, pw');
xtitle("Electrical power by component (HW-6)", "component index", "power [W]");
xgrid();
subplot(2,1,2);
bar(1:n, ms');
xtitle("Mass by component (HW-6)", "component index", "mass [g]");
xgrid();
try
    xs2png(1, "../figures/fig_power_mass_bars.png");
    xs2svg(1, "../figures/svg/fig_power_mass_bars.svg");
catch
    mprintf("  (PNG export skipped)\n");
end

scf(2); clf();
subplot(1,2,1);
bar([1 2], [P_tot POWER_LIMIT_W]);
xtitle("Power: used vs limit", "1 = used, 2 = limit", "power [W]");
xgrid();
subplot(1,2,2);
bar([1 2], [M_tot MASS_LIMIT_G]);
xtitle("Mass: used vs limit", "1 = used, 2 = limit", "mass [g]");
xgrid();
try
    xs2png(2, "../figures/fig_budget_margins.png");
    xs2svg(2, "../figures/svg/fig_budget_margins.svg");
catch
    mprintf("  (PNG export skipped)\n");
end

L = ["component,power_W,mass_g"];
for i = 1:n
    L = [L; msprintf("%s,%.3f,%.2f", names(i), pw(i), ms(i))];
end
L = [L; msprintf("TOTAL,%.3f,%.2f", P_tot, M_tot)];
L = [L; msprintf("LIMIT,%.3f,%.2f", POWER_LIMIT_W, MASS_LIMIT_G)];
L = [L; msprintf("MARGIN,%.3f,%.2f", P_marg, M_marg)];
mputl(L, "../results/power_budget.csv");
mprintf("Saved ../results/power_budget.csv and 2 figures.\n\n");
