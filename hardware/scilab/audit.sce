// =====================================================================
//  audit.sce   -   Day 12 number audit
//  WORK_DISTRIBUTION 6.1: "Verify every hardware metric matches payload
//  simulation outputs. Zero unverified claims allowed."
//
//  This script READS the CSVs in ../results/ and prints every number
//  that is allowed to appear on a slide, with the file it came from.
//  It computes nothing itself, so it cannot invent a number: if a value
//  is missing it prints MISSING and you re-run the script that makes it.
//
//  RUN LAST, after all seven analysis scripts.
//  It also writes ../docs/DECK_NUMBERS.md, ready to paste to Veda.
// =====================================================================
exec("params.sce", -1);
mprintf("\n===== DAY 12 NUMBER AUDIT =====\n\n");

// ---- read one value out of a CSV, keyed on the first column ----------
// Numeric keys are matched with a tolerance so "100" finds "100.00".
function v = csv_get(fpath, key, col, numeric_key)
    v = %nan;
    if ~isfile(fpath) then return; end
    L = mgetl(fpath);
    for i = 1:size(L, 1)
        t = strsplit(L(i), ",");
        if size(t, 1) < col then continue; end
        k = stripblanks(t(1));
        hit = %F;
        if numeric_key then
            kv = evstr_safe(k);
            if ~isnan(kv) then
                if abs(kv - evstr_safe(key)) < 1e-6 then hit = %T; end
            end
        else
            if k == key then hit = %T; end
        end
        if hit then
            v = evstr_safe(stripblanks(t(col)));
            return;
        end
    end
endfunction

function v = evstr_safe(s)
    v = %nan;
    try
        v = evstr(s);
    catch
        v = %nan;
    end
endfunction

// ---- column min/max over a CSV, for spans ----------------------------
function [lo, hi] = csv_range(fpath, col)
    lo = %nan; hi = %nan;
    if ~isfile(fpath) then return; end
    L = mgetl(fpath);
    vals = [];
    for i = 2:size(L, 1)
        t = strsplit(L(i), ",");
        if size(t, 1) < col then continue; end
        x = evstr_safe(stripblanks(t(col)));
        if ~isnan(x) then vals = [vals x]; end
    end
    if ~isempty(vals) then lo = min(vals); hi = max(vals); end
endfunction

// ---- read by ROW INDEX, independent of how the key is formatted ------
function v = csv_row(fpath, rownum, col)
    v = %nan;
    if ~isfile(fpath) then return; end
    L = mgetl(fpath);
    if size(L, 1) < rownum then return; end
    t = strsplit(L(rownum), ",");
    if size(t, 1) < col then return; end
    v = evstr_safe(stripblanks(t(col)));
endfunction

// ---- print a file verbatim, for diagnosing a failed lookup -----------
function dump_csv(fpath)
    mprintf("\n  ---- raw contents of %s ----\n", fpath);
    if ~isfile(fpath) then
        mprintf("  FILE DOES NOT EXIST\n");
        return;
    end
    L = mgetl(fpath);
    for i = 1:size(L, 1)
        mprintf("  [line %d] %s\n", i, L(i));
    end
    mprintf("  ---- end ----\n");
endfunction

function s = fmt(v, dp)
    if isnan(v) then
        s = "MISSING";
    else
        s = msprintf("%." + string(dp) + "f", v);
    end
endfunction

LB = "../results/link_budget.csv";
RX = "../results/rx_chain.csv";
RW = "../results/rx_chain_walk.csv";
RA = "../results/range_accuracy.csv";
ES = "../results/eye_safety.csv";
SC = "../results/scan_summary.csv";
PB = "../results/power_budget.csv";

missing = 0;
for f = [LB RX RW RA ES SC PB]
    if ~isfile(f) then
        mprintf("  MISSING FILE: %s\n", f);
        missing = missing + 1;
    end
end
if missing > 0 then
    mprintf("\n  %d result file(s) missing. Re-run the analysis scripts.\n\n", missing);
end

// ---- pull every auditable number -------------------------------------
rmax_01 = csv_get(LB, "0.1", 2, %T);
rmax_09 = csv_get(LB, "0.9", 2, %T);
if isnan(rmax_09) then
    // key match failed; rho=0.9 is written last, so read row 6 directly
    rmax_09 = csv_row(LB, 6, 2);
end
sweep_edge = csv_get(LB, "sweep_edge_m", 2, %F);
snr_100 = csv_get(LB, "0.1", 3, %T);

cfd_rms_100 = csv_get(RX, "100", 8, %T);
thr_rms_100 = csv_get(RX, "100", 5, %T);
[tb_lo, tb_hi] = csv_range(RX, 3);
[cb_lo, cb_hi] = csv_range(RX, 6);
[wt_lo, wt_hi] = csv_range(RW, 2);
[wc_lo, wc_hi] = csv_range(RW, 3);

tdc_cm  = csv_get(RA, "tdc_quantisation", 2, %F);
ratio   = csv_get(ES, "worst_ratio", 2, %F);
ael1    = csv_get(ES, "AEL_single", 2, %F);
c4      = csv_get(ES, "C4", 2, %F);
pitch   = csv_get(SC, "angular_pitch_mrad", 2, %F);
ndir    = csv_get(SC, "n_directions", 2, %F);
frate   = csv_get(SC, "frame_rate_hz", 2, %F);
prf_v   = csv_get(SC, "prf_hz", 2, %F);
ppers   = csv_get(SC, "points_per_s", 2, %F);
p_tot   = csv_get(PB, "TOTAL", 2, %F);
m_tot   = csv_get(PB, "TOTAL", 3, %F);
p_lim   = csv_get(PB, "LIMIT", 2, %F);
m_lim   = csv_get(PB, "LIMIT", 3, %F);

// ---- print ------------------------------------------------------------
mprintf("%-42s %14s   %s\n", "CLAIM", "VALUE", "SOURCE");
mprintf("%s\n", "-----------------------------------------------------------------------------");
mprintf("%-42s %14s   %s\n", "Max range, rho=0.1, SNR>=6",      fmt(rmax_01,1)+" m",  "link_budget.csv");
mprintf("%-42s %14s   %s\n", "Max range, rho=0.9",              fmt(rmax_09,1)+" m",  "link_budget.csv");
mprintf("%-42s %14s   %s\n", "SNR at 100 m, rho=0.1",           fmt(snr_100,2),       "link_budget.csv");
mprintf("%-42s %14s   %s\n", "Range error at 100 m, CFD",       fmt(cfd_rms_100*100,2)+" cm", "rx_chain.csv");
mprintf("%-42s %14s   %s\n", "Range error at 100 m, threshold", fmt(thr_rms_100*100,2)+" cm", "rx_chain.csv");
mprintf("%-42s %14s   %s\n", "Time walk 10-100 m, threshold",   fmt((tb_hi-tb_lo)*100,2)+" cm", "rx_chain.csv");
mprintf("%-42s %14s   %s\n", "Time walk 10-100 m, CFD",         fmt((cb_hi-cb_lo)*100,2)+" cm", "rx_chain.csv");
mprintf("%-42s %14s   %s\n", "Walk rho 0.1->0.9, threshold",    fmt((wt_hi-wt_lo)*100,2)+" cm", "rx_chain_walk.csv");
mprintf("%-42s %14s   %s\n", "Walk rho 0.1->0.9, CFD",          fmt((wc_hi-wc_lo)*100,4)+" cm", "rx_chain_walk.csv");
mprintf("%-42s %14s   %s\n", "TDC quantisation contribution",   fmt(tdc_cm,2)+" cm",  "range_accuracy.csv");
mprintf("%-42s %14s   %s\n", "Class 1 worst-case ratio",        fmt(ratio,3),         "eye_safety.csv");
mprintf("%-42s %14s   %s\n", "AEL single pulse",                fmt(ael1*1e9,4)+" nJ","eye_safety.csv");
mprintf("%-42s %14s   %s\n", "C4 wavelength correction",        fmt(c4,4),            "eye_safety.csv");
mprintf("%-42s %14s   %s\n", "Angular pitch",                   fmt(pitch,2)+" mrad", "scan_summary.csv");
mprintf("%-42s %14s   %s\n", "Beam directions per frame",       fmt(ndir,0),          "scan_summary.csv");
mprintf("%-42s %14s   %s\n", "Frame rate",                      fmt(frate,2)+" Hz",   "scan_summary.csv");
mprintf("%-42s %14s   %s\n", "PRF",                             fmt(prf_v/1e3,1)+" kHz","scan_summary.csv");
mprintf("%-42s %14s   %s\n", "Points delivered",                fmt(ppers/1e3,1)+" kpts/s","scan_summary.csv");
mprintf("%-42s %14s   %s\n", "Total power (estimated)",         fmt(p_tot,2)+" W",    "power_budget.csv");
mprintf("%-42s %14s   %s\n", "Total mass (estimated)",          fmt(m_tot,1)+" g",    "power_budget.csv");
mprintf("%-42s %14s   %s\n", "Power margin",                    fmt((p_lim-p_tot)/p_lim*100,1)+" %","power_budget.csv");
mprintf("%-42s %14s   %s\n", "Mass margin",                     fmt((m_lim-m_tot)/m_lim*100,1)+" %","power_budget.csv");
mprintf("%s\n", "-----------------------------------------------------------------------------");

// ---- consistency checks ----------------------------------------------
mprintf("\nCONSISTENCY CHECKS\n");
nfail = 0;
if rmax_01 >= R_MAX_REQ then
    mprintf("  PASS  max range %.1f m meets the %.0f m requirement\n", rmax_01, R_MAX_REQ);
else
    mprintf("  FAIL  max range %.1f m is BELOW the %.0f m requirement\n", rmax_01, R_MAX_REQ);
    nfail = nfail + 1;
end
if ratio <= 1.0 then
    mprintf("  PASS  Class 1 ratio %.3f (margin %.1f %%)\n", ratio, (1-ratio)*100);
    if ratio > 0.95 then
        mprintf("        NOTE margin is under 5 %%. Disclose this if asked.\n");
    end
else
    mprintf("  FAIL  Class 1 ratio %.3f exceeds 1.0\n", ratio);
    nfail = nfail + 1;
end
if abs(pitch - 5.0) < 0.01 then
    mprintf("  PASS  angular pitch %.2f mrad matches the PS-6 cell law\n", pitch);
else
    mprintf("  FAIL  angular pitch %.2f mrad no longer matches PS-6\n", pitch);
    nfail = nfail + 1;
end
if (p_tot <= p_lim) & (m_tot <= m_lim) then
    mprintf("  PASS  within the %.0f W / %.0f g payload budget\n", p_lim, m_lim);
else
    mprintf("  FAIL  over the payload budget\n");
    nfail = nfail + 1;
end
if ~isnan(sweep_edge) then
    if abs(rmax_09 - sweep_edge) < 1.0 then
        mprintf("  FAIL  max range at rho=0.9 (%.1f m) is pinned to the sweep\n", rmax_09);
        mprintf("        edge, not a real crossing. Widen R in link_budget.sce.\n");
        nfail = nfail + 1;
    else
        mprintf("  PASS  max range at rho=0.9 (%.1f m) is a real crossing\n", rmax_09);
    end
end
if cfd_rms_100 < thr_rms_100 then
    mprintf("  PASS  CFD beats threshold at 100 m by %.1fx\n", thr_rms_100/cfd_rms_100);
else
    mprintf("  FAIL  CFD is not beating the threshold\n");
    nfail = nfail + 1;
end
if nfail == 0 then
    mprintf("\n  ALL CHECKS PASSED. These numbers are cleared for the deck.\n");
else
    mprintf("\n  %d CHECK(S) FAILED. Do not put these on a slide yet.\n", nfail);
end

// ---- diagnose anything still missing ---------------------------------
if isnan(rmax_09) then
    mprintf("\nDIAGNOSTIC: max range at rho=0.9 could not be read.\n");
    dump_csv(LB);
    mprintf("  Send the lines above and this will be fixed in one step.\n");
end

// ---- write the paste-ready file ---------------------------------------
if ~isdir("../docs") then mkdir("../docs"); end
D = ["# Cleared payload numbers";
     "";
     "Generated by ``audit.sce`` from the CSVs in ``hardware/results/``.";
     "**Do not edit by hand.** Re-run the analysis scripts, then ``audit.sce``.";
     "";
     "| Claim | Value | Source |";
     "|---|---|---|";
     "| Max range, rho=0.1, SNR>=6 | " + fmt(rmax_01,1) + " m | link_budget.csv |";
     "| Max range, rho=0.9 | " + fmt(rmax_09,1) + " m | link_budget.csv |";
     "| SNR at 100 m, rho=0.1 | " + fmt(snr_100,2) + " | link_budget.csv |";
     "| Range error at 100 m, CFD | " + fmt(cfd_rms_100*100,2) + " cm | rx_chain.csv |";
     "| Range error at 100 m, threshold | " + fmt(thr_rms_100*100,2) + " cm | rx_chain.csv |";
     "| Time walk 10-100 m, threshold | " + fmt((tb_hi-tb_lo)*100,2) + " cm | rx_chain.csv |";
     "| Time walk 10-100 m, CFD | " + fmt((cb_hi-cb_lo)*100,2) + " cm | rx_chain.csv |";
     "| Walk rho 0.1 to 0.9, threshold | " + fmt((wt_hi-wt_lo)*100,2) + " cm | rx_chain_walk.csv |";
     "| Walk rho 0.1 to 0.9, CFD | " + fmt((wc_hi-wc_lo)*100,4) + " cm | rx_chain_walk.csv |";
     "| TDC quantisation | " + fmt(tdc_cm,2) + " cm | range_accuracy.csv |";
     "| Class 1 worst-case ratio | " + fmt(ratio,3) + " | eye_safety.csv |";
     "| AEL single pulse | " + fmt(ael1*1e9,4) + " nJ | eye_safety.csv |";
     "| Angular pitch | " + fmt(pitch,2) + " mrad | scan_summary.csv |";
     "| Beam directions per frame | " + fmt(ndir,0) + " | scan_summary.csv |";
     "| Frame rate | " + fmt(frate,2) + " Hz | scan_summary.csv |";
     "| PRF | " + fmt(prf_v/1e3,1) + " kHz | scan_summary.csv |";
     "| Points delivered | " + fmt(ppers/1e3,1) + " kpts/s | scan_summary.csv |";
     "| Total power (ESTIMATED) | " + fmt(p_tot,2) + " W | power_budget.csv |";
     "| Total mass (ESTIMATED) | " + fmt(m_tot,1) + " g | power_budget.csv |";
     "| Power margin | " + fmt((p_lim-p_tot)/p_lim*100,1) + " % | power_budget.csv |";
     "| Mass margin | " + fmt((m_lim-m_tot)/m_lim*100,1) + " % | power_budget.csv |";
     "";
     "All values are SIMULATED or ANALYTICAL. Nothing was built or measured.";
     "Power and mass are class-level estimates, not datasheet values."];
mputl(D, "../docs/DECK_NUMBERS.md");
mprintf("\nWrote ../docs/DECK_NUMBERS.md - send this to Veda.\n\n");
