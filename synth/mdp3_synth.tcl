# mdp3_synth.tcl — síntesis + implementación del parser CME MDP 3.0 (fase 4).
# Uso (Vivado batch, desde synth/):
#   vivado -mode batch -source mdp3_synth.tcl             # ambas variantes
#   vivado -mode batch -source mdp3_synth.tcl -tclargs 322  # solo 322 (CLO-M3T-01)
#   vivado -mode batch -source mdp3_synth.tcl -tclargs 156  # solo 156 (CLO-M3T-02)
# El owner pega el informe en synth/reports/mdp3/ (criterios CLO-M3T-01/02).
# Part objetivo: Kintex UltraScale+ (Vivado ML Standard gratuito). Decisión
# 002 — docs/decisiones/002-retarget-kintex-xcku3p.md.
set part xcku3p-ffva676-2L-e
# Top directo: rtl/parser/mdp3_parser.sv cabe en los 256 IOB del FFVA676
# (a diferencia de rtl/itch_chain.sv, que expone 896 y necesita wrapper).
set top mdp3_parser

# CLO-M3T-00: informes por variante en synth/reports/mdp3/. Este tcl ejecuta
# las dos variantes del criterio: DW=32 @ 322,265625 MHz (CLO-M3T-01) y
# DW=64 @ 156,25 MHz (CLO-M3T-02).

proc run_variant {dw outdir xdc} {
    global part top
    file mkdir $outdir
    create_project -in_memory -part $part
    read_verilog -sv ../rtl/parser/mdp3_parser.sv
    set_property generic "DW=$dw" [current_fileset]
    read_xdc $xdc

    synth_design -top $top -part $part
    write_checkpoint -force $outdir/post_synth.dcp
    report_utilization -hierarchical -file $outdir/util_synth.txt
    report_ram_utilization -file $outdir/ram_synth.txt
    report_clocks -file $outdir/clocks_synth.txt
    check_timing -verbose -file $outdir/check_timing_synth.txt
    report_methodology -file $outdir/methodology_synth.txt
    report_timing_summary -check_timing_verbose -report_unconstrained \
        -max_paths 10 -file $outdir/timing_synth.txt

    opt_design
    place_design
    phys_opt_design
    route_design
    write_checkpoint -force $outdir/post_route.dcp
    report_utilization -file $outdir/util_impl.txt
    report_ram_utilization -file $outdir/ram_impl.txt
    check_timing -verbose -file $outdir/check_timing_impl.txt
    report_methodology -file $outdir/methodology_impl.txt
    report_drc -file $outdir/drc_impl.txt
    report_timing_summary -check_timing_verbose -report_unconstrained \
        -max_paths 10 -file $outdir/timing_impl.txt

    set violating_paths [get_timing_paths -delay_type max -slack_lesser_than 0.0 \
        -max_paths 1 -quiet]
    if {[llength $violating_paths] != 0} {
        set wns [get_property SLACK [lindex $violating_paths 0]]
        error "MDP3 TIMING FAIL: WNS=$wns ns (se exige WNS>=0 y TNS=0)"
    }
    puts "== MDP3 SYNTH/IMPL OK (DW=$dw) — informes en $outdir =="
    close_project -quiet
}

# Variante CLO-M3T-01: 32-bit @ 322,265625 MHz (periodo 3,103 ns).
# Variante CLO-M3T-02 (regresión): 64-bit @ 156,25 MHz (periodo 6,400 ns).
# Selección por -tclargs (un solo run a la vez): 322, 156 o vacío (ambas).
set variants [expr {[llength $argv] == 0 ? {322 156} : $argv}]
foreach v $variants {
    if {$v == "322"} {
        run_variant 32 [file normalize ./reports/mdp3/322mhz] constraints/mdp3_322mhz.xdc
    } elseif {$v == "156"} {
        run_variant 64 [file normalize ./reports/mdp3/156mhz] constraints/mdp3_156mhz.xdc
    } else {
        error "Variante desconocida: $v (esperado: 322 o 156)"
    }
}

puts "== MDP3 SYNTH/IMPL OK — variantes ${variants} completas =="