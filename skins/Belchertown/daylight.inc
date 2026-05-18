## daylight module
## celestial module for weewx skins
## Copyright Tom Keffer, Matthew Wall
## See LICENSE.txt for your rights
#errorCatcher Echo
## If extended almanac information is available, do extra calculations.
#if $almanac.hasExtras
  #import locale
  #set $hour_short = $obs.label.hour_short if $obs.label.hour_short != "hour_short" else "h"
  #set $minute_short = $obs.label.minute_short if $obs.label.minute_short != "minute_short" else "m"
  #set $second_short = $obs.label.second_short if $obs.label.second_short != "second_short" else "s"
  #set $sunrise_ts = $almanac.sun.rise.raw
  #set $sunset_ts = $almanac.sun.set.raw
  #if $sunrise_ts and $sunset_ts
    #set $daylight_str = $obs.label.daylight
    #set $now = $current.dateTime.raw
    #set $today_daylight = $sunset_ts -  $sunrise_ts
    #set $seconds = $today_daylight
    #set $hours = $seconds // 3600
    #set $seconds %= 3600
    #set $minutes = $seconds // 60
    #set $seconds %= 60
    #set $yesterday = $now - 24*3600
    #set $yesterday_daylight = $almanac($almanac_time=$yesterday).sun.set.raw - $almanac($almanac_time=$yesterday).sun.rise.raw
    #set $difference = $today_daylight - $yesterday_daylight
    #if $difference
      #set $delta = abs($difference)
      #set $amt_minutes = (int($delta) % 3600) // 60
      #set $amt_seconds = int($delta) % 60
      #set $amt_str = "%d%s %d%s" % ($amt_minutes, $minute_short, $amt_seconds, $second_short)
      #if $difference > 0
        #if $obs.label.daylight_increase != "daylight_increase"
          #set $delta_str = "%s %s" % ( $amt_str, $obs.label.daylight_increase )
        #else
          #set $delta_str = "%s %s" % ( $amt_str, $obs.label.more_than_yesterday.split(' ', 1)[0] )
        #end if
      #else
        #if $obs.label.daylight_decrease != "daylight_decrease"
          #set $delta_str = "%s %s" % ( $amt_str, $obs.label.daylight_decrease )
        #else
          #set $delta_str = "%s %s" % ( $amt_str, $obs.label.less_than_yesterday.split(' ', 1)[0] )
        #end if
      #end if
      #set $daylight_str = "%s %s %s" % ( $daylight_str, ": ", $delta_str )
    #end if
  #end if
#end if
$daylight_str
