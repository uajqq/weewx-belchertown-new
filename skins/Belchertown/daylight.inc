## daylight module
## celestial module for weewx skins
## Copyright Tom Keffer, Matthew Wall
## See LICENSE.txt for your rights
#errorCatcher Echo
#from user.belchertown import build_daylight_change_string
#try
	#set $daylight_str = build_daylight_change_string($almanac, $current.dateTime.raw)
#except
	#set $unused_daylight_fallback = None
	#set $daylight_str = "Daylight: --"
#end try
$daylight_str
