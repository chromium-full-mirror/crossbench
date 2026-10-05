INCLUDE PERFETTO MODULE ext.web_power_rails;

SELECT
  power_rail_name,
  avg_power_mw
FROM ext_web_power_per_rail
WHERE power_rail_name IN (
    -- Main, external (PMIC loss included).
    -- 'power.rails.wifi.bt',
    -- 'power.VSYS_PWR_CAM_G1_uws',
    -- 'power.VSYS_PWR_CAM_G2_uws',
    -- 'power.VSYS_PWR_VBATT_uws',

    -- Main, internal (PMIC loss excluded).
    'power.rails.ldo.main.a',
    'power.rails.ldo.main.b',
    'power.rails.tpu',
    'power.S10M_VDD_AOC_uws',
    'power.S11M_VDD_CPU_M_uws',
    'power.S12M_VDD_CPU1_M_uws',
    'power.S1M_VDD_AMB_uws',
    'power.S2M_VDD_CPU2_uws',
    'power.S3M_VDD_CPU1_uws',
    'power.S4M_VDD_CPU_uws',
    'power.S5M_VDD_AUR_uws',
    'power.S9M_VDD_TPU_M_uws',

    -- Sub, external (PMIC loss included).
    -- 'power.rails.modem',
    -- 'power.rails.radio.frontend',
    -- 'power.VSYS_PWR_DISP_G1_uws',
    -- 'power.VSYS_PWR_DISP_G2_uws',

    -- Sub, internal (PMIC loss excluded).
    'power.rails.ddr.a',
    'power.rails.ddr.c',
    'power.rails.ldo.sub',
    'power.S10S_VDD_INFRA_MM_GPU_M_uws',
    -- 'power.S11S_UFS_VCC_uws',  -- Excluded from SOC_TOTAL.
    -- 'power.S12S_uws',  -- Excluded from SOC_TOTAL.
    'power.S1S_VDD_MM_uws',
    'power.S2S_VDD_GPU_uws',
    'power.S6S_LLDO2_uws',
    'power.S7S_MLDO_uws',
    'power.S8S_VDD_GMC_uws',
    'power.S9S_VDD_INFRA_uws'
  )
ORDER BY 1;
