## daylight module
## celestial module for weewx skins
## Copyright Tom Keffer, Matthew Wall
## See LICENSE.txt for your rights
#errorCatcher Echo
#from user.belchertown import build_daylight_change_string
#set $hour_short = "h"
#set $minute_short = "m"
#set $second_short = "s"
#set $more_than_yesterday_label = "more than yesterday"
#set $less_than_yesterday_label = "less than yesterday"
#set $daylight_label = "Daylight"
#set $same_as_yesterday_label = "same as yesterday"
#try
	#if $obs.label.hour_short != "hour_short"
		#set $hour_short = $obs.label.hour_short
	#end if
#except
	#set $unused_hour_short = None
#end try
#try
	#if $obs.label.minute_short != "minute_short"
		#set $minute_short = $obs.label.minute_short
	#end if
#except
	#set $unused_minute_short = None
#end try
#try
	#if $obs.label.second_short != "second_short"
		#set $second_short = $obs.label.second_short
	#end if
#except
	#set $unused_second_short = None
#end try
#try
	#if $obs.label.more_than_yesterday != "more_than_yesterday"
		#set $more_than_yesterday_label = $obs.label.more_than_yesterday
	#end if
#except
	#set $unused_more_label = None
#end try
#try
	#if $obs.label.less_than_yesterday != "less_than_yesterday"
		#set $less_than_yesterday_label = $obs.label.less_than_yesterday
	#end if
#except
	#set $unused_less_label = None
#end try
#try
	#if $obs.label.daylight != "daylight"
		#set $daylight_label = $obs.label.daylight
	#end if
#except
	#set $unused_daylight_label = None
#end try
#try
	#if $obs.label.same_as_yesterday != "same_as_yesterday"
		#set $same_as_yesterday_label = $obs.label.same_as_yesterday
	#end if
#except
	#set $unused_same_label = None
#end try
#try
	#set $daylight_str = build_daylight_change_string($almanac, $current.dateTime.raw, $hour_short, $minute_short, $second_short, $more_than_yesterday_label, $less_than_yesterday_label, $daylight_label, $same_as_yesterday_label)
#except
	#set $unused_daylight_fallback = None
	#set $daylight_str = "%s: --" % $daylight_label
#end try
$daylight_str
