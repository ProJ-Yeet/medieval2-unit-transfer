@echo off
pushd "%~dp0"
echo Removing files which regenerate on launch to make changes effective...
if exist data\world\maps\base\map.rwm del /F/s/q data\world\maps\base\map.rwm
if exist data\world\maps\campaign\custom\Shattered_Alliances\map.rwm del /F/s/q data\world\maps\campaign\custom\Shattered_Alliances\map.rwm
if exist data\text\export_units.txt.strings.bin del /F/s/q data\text\export_units.txt.strings.bin
if exist data\text\export_buildings.txt.strings.bin del /F/s/q data\text\export_buildings.txt.strings.bin
if exist data\text\imperial_campaign_regions_and_settlement_names.txt.strings.bin del /F/s/q data\text\imperial_campaign_regions_and_settlement_names.txt.strings.bin
if exist data\text\shattered_alliances_regions_and_settlement_names.txt.strings.bin del /F/s/q data\text\shattered_alliances_regions_and_settlement_names.txt.strings.bin
if exist data\text\historic_events.txt.strings.bin del /F/s/q data\text\historic_events.txt.strings.bin
if exist data\text\expanded.txt.strings.bin del /F/s/q data\text\expanded.txt.strings.bin
if exist data\text\battle_descriptions.txt.strings.bin del /F/s/q data\text\battle_descriptions.txt.strings.bin
if exist data\text\building_battle.txt.strings.bin del /F/s/q data\text\building_battle.txt.strings.bin
if exist data\text\campaign_descriptions.txt.strings.bin del /F/s/q data\text\campaign_descriptions.txt.strings.bin
if exist data\text\climates.txt.strings.bin del /F/s/q data\text\climates.txt.strings.bin
if exist data\text\cursor_action_tooltips.txt.strings.bin del /F/s/q data\text\cursor_action_tooltips.txt.strings.bin
if exist data\text\diplomacy.txt.strings.bin del /F/s/q data\text\diplomacy.txt.strings.bin
if exist data\text\diplomacy_speech.txt.strings.bin del /F/s/q data\text\diplomacy_speech.txt.strings.bin
if exist data\text\event_strings.txt.strings.bin del /F/s/q data\text\event_strings.txt.strings.bin
if exist data\text\event_titles.txt.strings.bin del /F/s/q data\text\event_titles.txt.strings.bin
if exist data\text\export_advice.txt.strings.bin del /F/s/q data\text\export_advice.txt.strings.bin
if exist data\text\export_ancillaries.txt.strings.bin del /F/s/q data\text\export_ancillaries.txt.strings.bin
if exist data\text\export_VnVs.txt.strings.bin del /F/s/q data\text\export_VnVs.txt.strings.bin
if exist data\text\menu_english.txt.strings.bin del /F/s/q data\text\menu_english.txt.strings.bin
if exist data\text\missions.txt.strings.bin del /F/s/q data\text\missions.txt.strings.bin
if exist data\text\names.txt.strings.bin del /F/s/q data\text\names.txt.strings.bin
if exist data\text\quotes.txt.strings.bin del /F/s/q data\text\quotes.txt.strings.bin
if exist data\text\rebel_faction_descr.txt.strings.bin del /F/s/q data\text\rebel_faction_descr.txt.strings.bin
if exist data\scripts\show_me\G5Script2.txt del /F/s/q data\scripts\show_me\G5Script2.txt
if exist data\scripts\show_me\background_script.txt del /F/s/q data\scripts\show_me\background_script.txt
if exist data\terrain\aerial_map\sea\colour.tga del /F/s/q data\terrain\aerial_map\sea\colour.tga
if exist data\terrain\aerial_map\sea\colour.tga.dds del /F/s/q data\terrain\aerial_map\sea\colour.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame0.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame0.tga
if exist data\terrain\aerial_map\sea\surf_frame0.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame0.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame1.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame1.tga
if exist data\terrain\aerial_map\sea\surf_frame1.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame1.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame2.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame2.tga
if exist data\terrain\aerial_map\sea\surf_frame2.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame2.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame3.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame3.tga
if exist data\terrain\aerial_map\sea\surf_frame3.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame3.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame4.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame4.tga
if exist data\terrain\aerial_map\sea\surf_frame4.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame4.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame5.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame5.tga
if exist data\terrain\aerial_map\sea\surf_frame5.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame5.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame6.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame6.tga
if exist data\terrain\aerial_map\sea\surf_frame6.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame6.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame7.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame7.tga
if exist data\terrain\aerial_map\sea\surf_frame7.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame7.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame8.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame8.tga
if exist data\terrain\aerial_map\sea\surf_frame8.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame8.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame9.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame9.tga
if exist data\terrain\aerial_map\sea\surf_frame9.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame9.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame10.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame10.tga
if exist data\terrain\aerial_map\sea\surf_frame10.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame10.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame11.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame11.tga
if exist data\terrain\aerial_map\sea\surf_frame11.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame11.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame12.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame12.tga
if exist data\terrain\aerial_map\sea\surf_frame12.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame12.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame13.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame13.tga
if exist data\terrain\aerial_map\sea\surf_frame13.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame13.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame14.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame14.tga
if exist data\terrain\aerial_map\sea\surf_frame14.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame14.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame15.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame15.tga
if exist data\terrain\aerial_map\sea\surf_frame15.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame15.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame16.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame16.tga
if exist data\terrain\aerial_map\sea\surf_frame16.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame16.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame17.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame17.tga
if exist data\terrain\aerial_map\sea\surf_frame17.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame17.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame18.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame18.tga
if exist data\terrain\aerial_map\sea\surf_frame18.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame18.tga.dds
if exist data\terrain\aerial_map\sea\surf_frame19.tga del /F/s/q data\terrain\aerial_map\sea\surf_frame19.tga
if exist data\terrain\aerial_map\sea\surf_frame19.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf_frame19.tga.dds
if exist data\terrain\aerial_map\sea\surface.tga del /F/s/q data\terrain\aerial_map\sea\surface.tga
if exist data\terrain\aerial_map\sea\surface.tga.dds del /F/s/q data\terrain\aerial_map\sea\surface.tga.dds
if exist data\terrain\aerial_map\sea\water.tga del /F/s/q data\terrain\aerial_map\sea\water.tga
if exist data\terrain\aerial_map\sea\water.tga.dds del /F/s/q data\terrain\aerial_map\sea\water.tga.dds
if exist data\terrain\aerial_map\sea\beach_strip.tga.dds del /F/s/q data\terrain\aerial_map\sea\beach_strip.tga.dds
if exist data\terrain\aerial_map\sea\sky_environment_summer.tga.dds del /F/s/q data\terrain\aerial_map\sea\sky_environment_summer.tga.dds
if exist data\terrain\aerial_map\sea\surf2b.tga.dds del /F/s/q data\terrain\aerial_map\sea\surf2b.tga.dds
if exist data\terrain\aerial_map\sea\waves.tga.dds del /F/s/q data\terrain\aerial_map\sea\waves.tga.dds
if exist data\models_strat\residences\faction_variants\denmark\gondor_t3_stronghold.cas del /F/s/q data\models_strat\residences\faction_variants\denmark\gondor_t3_stronghold.cas
if exist "data\models_strat\residences\faction_variants\denmark\gondor_t3_stronghold - Deadman's Dike (Ruined Fornost).txt" del /F/s/q "data\models_strat\residences\faction_variants\denmark\gondor_t3_stronghold - Deadman's Dike (Ruined Fornost).txt"
if exist data\models_strat\residences\faction_variants\denmark\textures\fornost_ruined_buildings.tga del /F/s/q data\models_strat\residences\faction_variants\denmark\textures\fornost_ruined_buildings.tga
if exist data\models_strat\residences\faction_variants\denmark\textures\fornost_ruined_buildings.tga.dds del /F/s/q data\models_strat\residences\faction_variants\denmark\textures\fornost_ruined_buildings.tga.dds
if exist data\models_strat\residences\faction_variants\denmark\textures\fornost_ruined_vines.tga del /F/s/q data\models_strat\residences\faction_variants\denmark\textures\fornost_ruined_vines.tga
if exist data\models_strat\residences\faction_variants\denmark\textures\fornost_ruined_vines.tga.dds del /F/s/q data\models_strat\residences\faction_variants\denmark\textures\fornost_ruined_vines.tga.dds
if exist data\models_strat\residences\faction_variants\denmark\textures\stone_ruins.tga del /F/s/q data\models_strat\residences\faction_variants\denmark\textures\stone_ruins.tga
if exist data\models_strat\residences\faction_variants\denmark\textures\stone_ruins.tga.dds del /F/s/q data\models_strat\residences\faction_variants\denmark\textures\stone_ruins.tga.dds
if exist data\models_strat\residences\faction_variants\france\orc_t3_stronghold.cas del /F/s/q data\models_strat\residences\faction_variants\france\orc_t3_stronghold.cas
if exist "data\models_strat\residences\faction_variants\france\orc_t3_stronghold - Deadman's Dike (Ruined Fornost).txt" del /F/s/q "data\models_strat\residences\faction_variants\france\orc_t3_stronghold - Deadman's Dike (Ruined Fornost).txt"
if exist data\models_strat\residences\faction_variants\france\textures\fornost_ruined_buildings.tga del /F/s/q data\models_strat\residences\faction_variants\france\textures\fornost_ruined_buildings.tga
if exist data\models_strat\residences\faction_variants\france\textures\fornost_ruined_buildings.tga.dds del /F/s/q data\models_strat\residences\faction_variants\france\textures\fornost_ruined_buildings.tga.dds
if exist data\models_strat\residences\faction_variants\france\textures\fornost_ruined_vines.tga del /F/s/q data\models_strat\residences\faction_variants\france\textures\fornost_ruined_vines.tga
if exist data\models_strat\residences\faction_variants\france\textures\fornost_ruined_vines.tga.dds del /F/s/q data\models_strat\residences\faction_variants\france\textures\fornost_ruined_vines.tga.dds
if exist data\models_strat\residences\faction_variants\france\textures\stone_ruins.tga del /F/s/q data\models_strat\residences\faction_variants\france\textures\stone_ruins.tga
if exist data\models_strat\residences\faction_variants\france\textures\stone_ruins.tga.dds del /F/s/q data\models_strat\residences\faction_variants\france\textures\stone_ruins.tga.dds
if exist data\models_strat\residences\faction_variants\hre\orc_t2_castle.cas del /F/s/q data\models_strat\residences\faction_variants\hre\orc_t2_castle.cas
if exist "data\models_strat\residences\faction_variants\hre\orc_t2_castle - Annon-en-Orod.txt" del /F/s/q "data\models_strat\residences\faction_variants\hre\orc_t2_castle - Annon-en-Orod.txt"
if exist data\models_strat\residences\faction_variants\hre\textures\mountain_grass.tga del /F/s/q data\models_strat\residences\faction_variants\hre\textures\mountain_grass.tga
if exist data\models_strat\residences\faction_variants\hre\textures\mountain_grass.tga.dds del /F/s/q data\models_strat\residences\faction_variants\hre\textures\mountain_grass.tga.dds
if exist data\models_strat\residences\faction_variants\hre\textures\goblin_cave.tga del /F/s/q data\models_strat\residences\faction_variants\hre\textures\goblin_cave.tga
if exist data\models_strat\residences\faction_variants\hre\textures\goblin_cave.tga.dds del /F/s/q data\models_strat\residences\faction_variants\hre\textures\goblin_cave.tga.dds
if exist data\models_strat\residences\faction_variants\hre\textures\goblin_mud.tga del /F/s/q data\models_strat\residences\faction_variants\hre\textures\goblin_mud.tga
if exist data\models_strat\residences\faction_variants\hre\textures\goblin_mud.tga.dds del /F/s/q data\models_strat\residences\faction_variants\hre\textures\goblin_mud.tga.dds
if exist data\models_strat\residences\faction_variants\hre\textures\goblin_rock.tga del /F/s/q data\models_strat\residences\faction_variants\hre\textures\goblin_rock.tga
if exist data\models_strat\residences\faction_variants\hre\textures\goblin_rock.tga.dds del /F/s/q data\models_strat\residences\faction_variants\hre\textures\goblin_rock.tga.dds
if exist data\models_strat\residences\faction_variants\hre\textures\goblin_stone.tga del /F/s/q data\models_strat\residences\faction_variants\hre\textures\goblin_stone.tga
if exist data\models_strat\residences\faction_variants\hre\textures\goblin_stone.tga.dds del /F/s/q data\models_strat\residences\faction_variants\hre\textures\goblin_stone.tga.dds
if exist data\models_strat\residences\faction_variants\hre\textures\goblin_tower.tga del /F/s/q data\models_strat\residences\faction_variants\hre\textures\goblin_tower.tga
if exist data\models_strat\residences\faction_variants\hre\textures\goblin_tower.tga.dds del /F/s/q data\models_strat\residences\faction_variants\hre\textures\goblin_tower.tga.dds
if exist data\models_strat\residences\faction_variants\hre\textures\orc_strat_v13.tga del /F/s/q data\models_strat\residences\faction_variants\hre\textures\orc_strat_v13.tga
if exist data\models_strat\residences\faction_variants\hre\textures\orc_strat_v13.tga.dds del /F/s/q data\models_strat\residences\faction_variants\hre\textures\orc_strat_v13.tga.dds
if exist  "data\models_strat\residences\faction_variants\khand\evil_men_t3_stronghold - Gobel Tolfalas.txt" del /F/s/q "data\models_strat\residences\faction_variants\khand\evil_men_t3_stronghold - Gobel Tolfalas.txt"
if exist "data\models_strat\residences\faction_variants\slave\northmen_t5_large_city - Annuminas.txt" del /F/s/q "data\models_strat\residences\faction_variants\slave\northmen_t5_large_city - Annuminas.txt"
if exist data\world\maps\battle\Azanulbizar del /F /S /Q data\world\maps\battle\Azanulbizar
if exist data\world\maps\battle\Battle_of_the_Five_Armies del /F /S /Q data\world\maps\battle\Battle_of_the_Five_Armies
if exist data\world\maps\battle\Fields_of_Celebrant del /F /S /Q data\world\maps\battle\Fields_of_Celebrant
if exist data\world\maps\battle\The_Siege_of_Cair_Andros del /F /S /Q data\world\maps\battle\The_Siege_of_Cair_Andros
if exist dac.bat del /F /S /Q dac.bat
echo Cleaned
pause
