LowKickPowerByWeight:
	;    BP, min weight / 10 (kg → same units as BODY_WEIGHT tenths-kilogram scale)
	dbw 120, 2000 ; 200.0 kg+
	dbw 100, 1000 ; 100.0–199.9 kg
	dbw  80, 500 ; 50.0–99.9 kg
	dbw  60, 250 ; 25.0–49.9 kg
	dbw  40, 100 ; 10.0–24.9 kg
	dbw  20, 0   ; <10.0 kg
