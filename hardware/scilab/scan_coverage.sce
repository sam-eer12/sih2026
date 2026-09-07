// =====================================================================
//  scan_coverage.sce   -   PRD HW-5
//  MEMS scan pattern -> angular sampling -> point density vs range,
//  tested against the PS-6 cell sizes in config.yaml.
//
//  THE KEY RESULT: PS-6 asks for 5 cm cells at 10 m and 50 cm cells at
//  100 m. Both are 5 mrad. The software's variable-resolution law is a
//  CONSTANT ANGULAR PITCH, which is exactly what a scanner produces for
//  free. The payload and the grid engine agree by construction.
// =====================================================================
exec("params.sce", -1);
ensure_dirs();
mprintf("\n===== SCAN COVERAGE (HW-5) =====\n\n");

// ---- the PS-6 -> angle result ----------------------------------------
mprintf("PS-6 cell law expressed as an angle\n");
mprintf("  at r = %5.1f m, cell %.2f m -> %.3f mrad\n", R_KNEE, S_MIN, S_MIN/R_KNEE*1e3);
mprintf("  at r = %5.1f m, cell %.2f m -> %.3f mrad\n", R_MAX_REQ, S_MAX, S_MAX/R_MAX_REQ*1e3);
mprintf("  => required angular pitch is CONSTANT at %.2f mrad\n\n", ANG_PITCH*1e3);

if abs(S_MIN/R_KNEE - S_MAX/R_MAX_REQ) > 1e-9 then
    mprintf("  WARNING: the two ends no longer agree. config.yaml changed.\n");
end

// ---- scan geometry ----------------------------------------------------
az = FOV_AZ_DEG*%pi/180;
el = FOV_EL_DEG*%pi/180;
n_az = ceil(az/ANG_PITCH);
n_el = ceil(el/ANG_PITCH);
n_dir = n_az*n_el;
t_dir = N_ACC * T_I_GROUP;      // accumulation pulses spaced by Ti
t_frame = n_dir * t_dir;
frame_rate = 1/t_frame;
prf_needed = n_dir * N_ACC * frame_rate;
pts_per_s = n_dir * frame_rate;

mprintf("Scan geometry\n");
mprintf("  field of view            %.0f x %.0f deg\n", FOV_AZ_DEG, FOV_EL_DEG);
mprintf("  angular pitch            %.2f mrad\n", ANG_PITCH*1e3);
mprintf("  beam directions          %.0f az x %.0f el = %.0f\n", n_az, n_el, n_dir);
mprintf("  accumulation per dir     %d pulses spaced %.1f us\n", N_ACC, T_I_GROUP*1e6);
mprintf("  dwell per direction      %.1f us\n", t_dir*1e6);
mprintf("  frame time               %.1f ms\n", t_frame*1e3);
mprintf("  FRAME RATE               %.2f Hz\n", frame_rate);
mprintf("  REQUIRED PRF             %.1f kHz\n", prf_needed/1e3);
mprintf("  points delivered         %.1f kpts/s\n", pts_per_s/1e3);
mprintf("  laser duty cycle         %.4f %%\n", prf_needed*PULSE_FWHM*100);
mprintf("  average optical power    %.3f mW\n\n", P_PEAK*PULSE_FWHM*prf_needed*1e3);

if abs(prf_needed - PRF)/PRF > 0.02 then
    mprintf("  NOTE: params.sce has PRF = %.1f kHz but this geometry needs\n", PRF/1e3);
    mprintf("        %.1f kHz. Update params.sce.\n\n", prf_needed/1e3);
end

// ---- point density vs range ------------------------------------------
R = linspace(2, 150, 500);
spot_pitch = ANG_PITCH * R;                 // spacing between adjacent spots [m]
cell_size  = min(max(S_MIN, 0.005*R), S_MAX); // PS-6 cell size law
pts_per_cell = (cell_size ./ spot_pitch).^2;
density = 1 ./ (spot_pitch.^2);             // points per m^2 of surface

scf(1); clf();
plot(R, spot_pitch*100, "b-");
plot(R, cell_size*100, "r--");
legend(["LiDAR spot pitch"; "PS-6 cell size"], 2);
xtitle("Angular sampling vs PS-6 cell size (HW-5)", "range [m]", "size [cm]");
xgrid();
try
    xs2png(1, "../figures/fig_scan_pitch.png");
    xs2svg(1, "../figures/svg/fig_scan_pitch.svg");
catch
    mprintf("  (PNG export skipped)\n");
end

scf(2); clf();
plot(R, density, "b-");
xtitle("Point density on the target surface vs range", ..
       "range [m]", "points per m^2");
xgrid();
try
    xs2png(2, "../figures/fig_scan_density.png");
    xs2svg(2, "../figures/svg/fig_scan_density.svg");
catch
    mprintf("  (PNG export skipped)\n");
end

scf(3); clf();
plot(R, pts_per_cell, "b-");
plot([2 150], [1 1], "r--");
legend(["points landing in one PS-6 cell"; "one point per cell"], 1);
xtitle("Points per PS-6 grid cell vs range", "range [m]", "points per cell [-]");
xgrid();
try
    xs2png(3, "../figures/fig_scan_pts_per_cell.png");
    xs2svg(3, "../figures/svg/fig_scan_pts_per_cell.svg");
catch
    mprintf("  (PNG export skipped)\n");
end

mprintf("Point density check against PS-6\n");
for r = [5 10 30 50 100]
    sp = ANG_PITCH*r;
    cs = min(max(S_MIN, 0.005*r), S_MAX);
    mprintf("  r=%5.1f m : spot pitch %5.1f cm, PS-6 cell %5.1f cm, %5.2f pts/cell", ..
            r, sp*100, cs*100, (cs/sp)^2);
    if sp <= cs*1.001 then mprintf("  OK\n"); else mprintf("  UNDER-SAMPLED\n"); end
end

mprintf("\n  Inside r_knee the grid holds cells at %.0f cm while the beam\n", S_MIN*100);
mprintf("  pitch shrinks to %.1f cm at 5 m, so near cells get MORE than one\n", ANG_PITCH*5*100);
mprintf("  point. That is the correct behaviour: PS-6 caps near-field cell\n");
mprintf("  size at s_min, it does not ask the sensor to sample coarser.\n\n");

L = ["range_m,spot_pitch_m,ps6_cell_m,pts_per_cell,density_per_m2"];
for i = 1:10:500
    L = [L; msprintf("%.2f,%.5f,%.5f,%.4f,%.4f", R(i), spot_pitch(i), ..
         cell_size(i), pts_per_cell(i), density(i))];
end
mputl(L, "../results/scan_coverage.csv");

// Summary row set, so the Day-12 audit can read the scan numbers from a
// file instead of someone copying them off the console.
S = ["quantity,value,unit";
     msprintf("angular_pitch,%.6f,rad", ANG_PITCH);
     msprintf("angular_pitch_mrad,%.4f,mrad", ANG_PITCH*1e3);
     msprintf("fov_az_deg,%.2f,deg", FOV_AZ_DEG);
     msprintf("fov_el_deg,%.2f,deg", FOV_EL_DEG);
     msprintf("n_directions,%.0f,-", n_dir);
     msprintf("frame_rate_hz,%.4f,Hz", frame_rate);
     msprintf("prf_hz,%.1f,Hz", prf_needed);
     msprintf("points_per_s,%.1f,pts/s", pts_per_s);
     msprintf("duty_cycle_pct,%.6f,%%", prf_needed*PULSE_FWHM*100);
     msprintf("avg_optical_mW,%.4f,mW", P_PEAK*PULSE_FWHM*prf_needed*1e3)];
mputl(S, "../results/scan_summary.csv");
mprintf("Saved ../results/scan_coverage.csv and 3 figures.\n\n");
